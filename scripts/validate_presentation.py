"""Validate native 1:100 titles, sheet arrangement, front sheets and socket legends.
Inputs: native_details.json (blocks/layers), raw_index.json (handle -> entget string),
sheets.json: ordered [{frameHandle,name,kind,floor,number}].
Kinds: directory, notes, system, lighting, socket, weak, roof, ground.
Use --template-only only when surveying legacy source DWGs. Final review still
compares complete pages and distribution units visually against the sample.
"""
import argparse,json,re
from pathlib import Path
RANK={k:i for i,k in enumerate(['directory','notes','system','lighting','socket','weak','roof','ground'])}
PLAN={'lighting','socket','weak','roof','ground'}
FRONT_MANIFEST = Path(__file__).resolve().parents[1] / 'references/front-sheet-manifest.json'
SOCKET_MANIFEST = FRONT_MANIFEST.with_name('socket-legend-manifest.json')
FRONT_KINDS = {'directory':'directory', 'notes':'notes', 'distribution':'system', 'general_system':'system'}
OPENING_CODES = re.compile(
    r'^(?:[A-Z]{0,4}[MC][A-Z]{0,2}|DOOR|WINDOW|WIN)[\s_-]*[0-9]{3,6}(?:[A-Z]|[-_]\d{1,3})?$',
    re.IGNORECASE)
def scalar(raw,code):
 m=re.search(r'\('+str(code)+r' \. ([^\)]+)\)',raw)
 if not m:return None
 try:return float(m[1])
 except ValueError:return m[1].strip('"')
def contained(b,f):
 return b and all(f[0][k]-.01<=b[0][k]<=b[1][k]<=f[1][k]+.01 for k in (0,1))
def front_sheet_errors(details, sheets, manifest):
    """Require the template's full front sequence and native general-system blocks."""
    pages = [page for asset in manifest['assets'].values() for page in asset['pages']]
    expected = [(page['name'], FRONT_KINDS[page['role']]) for page in pages]
    actual = [(sheet['name'], sheet['kind']) for sheet in sheets[:len(expected)]]
    errors = []
    if actual != expected:
        errors.append('V09 前置页缺失、改名或排序有误，应为 ' + ' → '.join(name for name, _ in expected))
    for page in pages:
        if page['role'] != 'general_system':
            continue
        matching = [sheet for sheet in sheets if sheet['name'] == page['name'] and sheet['kind'] == 'system']
        if len(matching) != 1:
            errors.append(f"V09 缺少独立且唯一的通用页 {page['name']}")
            continue
        blocks = details['blocks']
        model = blocks['*Model_Space']
        frame = next((e.get('bbox') for e in model if e['h'] == matching[0].get('frameHandle')), None)
        if not frame:
            errors.append(f"V09 无法从原生 DWG 读取 {page['name']} 的图框")
            continue
        entities = [entity for entity in model if contained(entity.get('bbox'), frame)]
        present = {re.sub(r'^(?:\$\d+\$)+', '', entity['block'])
                   for entity in entities if entity['type'] == 'INSERT' and entity.get('block')
                   and blocks.get(entity['block'])}
        for missing in sorted(set(page['anchors'].values()) - present):
            errors.append(f"V09 {page['name']} 图框内缺少样板原生示意块 {missing}")
        excluded = set(page.get('excludedModelLayers', []))
        if any(re.sub(r'^(?:\$\d+\$)+', '', entity['layer']) in excluded for entity in entities):
            errors.append(f"V09 {page['name']} 混入应放在系统图一的楼层配电图元")
    return errors

def socket_legend_errors(details, sheets, manifest):
    socket_sheets = [sheet for sheet in sheets if sheet['kind'] == 'socket']
    if not socket_sheets:
        return []
    blocks = details['blocks']
    name = manifest['block']
    cells = blocks.get(name, [])
    errors = []
    if len(cells) != manifest['entityCount']:
        errors.append(f'V10 插座图例应整组继承 {manifest["entityCount"]} 个原生图元，实有 {len(cells)} 个')

    def normalized(value):
        return ''.join(value.split())

    available = {normalized(e.get('text', '')): e
                 for e in cells if e['type'] in ('TEXT', 'MTEXT')}
    for line in manifest['headers'] + manifest['rows']:
        if normalized(line) not in available:
            errors.append(f'V10 插座图例缺少样板原文 {line}')

    model = blocks['*Model_Space']
    model_by_handle = {entity['h']: entity for entity in model}
    inserts = [e for e in model if e['type'] == 'INSERT' and e.get('block') == name]
    for sheet in socket_sheets:
        frame = model_by_handle.get(sheet.get('frameHandle'), {}).get('bbox')
        matching = [e for e in inserts if frame and contained(e.get('bbox'), frame)]
        if len(matching) != 1:
            errors.append(f'V10 {sheet["name"]} 的图框内应有一套完整图例，实有 {len(matching)} 套')
            continue
        scale_x, scale_y = matching[0]['scale'][:2]
        if scale_x <= 0 or abs(scale_x - scale_y) > .001:
            errors.append(f'V11 {sheet["name"]} 的图例应按原样板比例等比放置')
        min_height = manifest['minimumBodyTextHeight'] * .995
        if any(available.get(normalized(row), {}).get('height', 0) * scale_y < min_height
               for row in manifest['rows']):
            errors.append(f'V11 {sheet["name"]} 的图例说明字高小于样板')
    return errors


def background_opening_errors(details):
    """Reject original number-bearing openings and loose codes inside electrical backgrounds."""
    blocks = details['blocks']
    errors = []
    visited = set()

    def check(owner):
        if owner in visited:
            return
        visited.add(owner)
        for entity in blocks.get(owner, []):
            kind = entity['type']
            if kind in {'TCH_OPENING', 'TCH_DOOR', 'TCH_WINDOW'}:
                errors.append(f'V11 电气底图 {owner} 残留会生成编号的天正门窗 {entity["h"]}')
            for item in [entity, *entity.get('attrs', [])]:
                layer = item['layer'].upper()
                labels = [item.get('text', ''), *item.get('nativeText', [])]
                if ('AXIS' not in layer and '轴号' not in layer
                        and any(label and (OPENING_CODES.fullmatch(label.strip())
                                         or any(flag in layer for flag in ('WINDOW', 'DOOR', '门窗')))
                                for label in labels)):
                    errors.append(f'V11 电气底图 {owner} 残留门窗编号 {item["h"]} {labels}')
            if kind == 'INSERT':
                check(entity.get('block'))

    for entity in blocks['*Model_Space']:
        if entity['type'] == 'INSERT' and entity.get('layer') == 'BASE':
            check(entity.get('block'))
    return errors


def validate(details,raw,sheets,*,template_only=False,front_manifest=None):
 m=details['blocks']['*Model_Space'];mh={z['h']:z for z in m};errors=[];frames=[];titles=[]
 for sh in sheets:
  e=mh.get(sh['frameHandle']);b=e.get('bbox') if e else None
  if not b:errors.append('Missing frame '+sh['frameHandle']);continue
  frames.append(b)
  if not template_only:
   units_per_mm=float(sh.get('modelUnitsPerPaperMm',100))
   short_side,long_side=sorted((b[1][axis]-b[0][axis])/units_per_mm for axis in (0,1))
   if abs(short_side-297)>.3 or abs(long_side-420)>.3:
    errors.append(f"V29 {sh['name']} 实测外框 {short_side:.1f} × {long_side:.1f} mm，应为 A3")
  if sh['kind'] in PLAN:
   ts=[z for z in m if z['type']=='TCH_DRAWINGNAME' and contained(z.get('bbox'),b)]
   if len(ts)!=1:errors.append(sh['name']+': expected one native plan title');continue
   z=ts[0];r=raw.get(z['h'],'');titles.append(z['h'])
   if scalar(r,1)!=sh['name']:errors.append(sh['name']+': name differs')
   expected={40:7,41:5,42:.7,43:.6,47:100,70:4,290:1}
   for code,want in expected.items():
    got=scalar(r,code)
    if not isinstance(got,(int,float)) or abs(got-want)>1e-6:errors.append(sh['name']+': DXF '+str(code)+' = '+str(got)+', expected '+str(want))
   if scalar(r,2)!='1:100':errors.append(sh['name']+': displayed ratio differs')
 x=frames[0][0][0] if frames else 0
 if any(abs(b[0][0]-x)>.01 for b in frames):errors.append('Frame left edges not aligned')
 if any(abs(frames[i][0][1]-frames[i+1][1][1])>.01 for i in range(len(frames)-1)):errors.append('Frames not vertically contiguous in manifest order')
 ranks=[RANK[s['kind']] for s in sheets]
 if ranks!=sorted(ranks):errors.append('Sheet categories not in sample order')
 for kind in ['lighting','socket','weak']:
  floors=[s['floor'] for s in sheets if s['kind']==kind]
  if floors!=sorted(floors):errors.append(kind+': floors not ascending')
 nums=[int(re.search(r'(\d+)$',s['number'])[1]) for s in sheets]
 if not nums or nums!=list(range(nums[0],nums[0]+len(nums))):errors.append('Sheet numbers not sequential')
 if not template_only:
  manifest=front_manifest if front_manifest is not None else json.loads(FRONT_MANIFEST.read_text('utf-8-sig'))
  errors.extend(front_sheet_errors(details,sheets,manifest))
  socket_manifest=json.loads(SOCKET_MANIFEST.read_text('utf-8-sig'))
  errors.extend(socket_legend_errors(details,sheets,socket_manifest))
  errors.extend(background_opening_errors(details))
 return dict(passed=not errors,errors=errors,checkedFrames=len(frames),checkedNativeTitles=len(titles),scope='Template survey' if template_only else 'Front sheets, socket legends, architectural backgrounds, native titles and sheet arrangement')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--details',required=True,type=Path)
 p.add_argument('--raw',required=True,type=Path)
 p.add_argument('--sheets',required=True,type=Path)
 p.add_argument('--output',type=Path)
 mode=p.add_mutually_exclusive_group()
 mode.add_argument('--template-only',action='store_true',help='Survey an input sample. This does not check delivery requirements.')
 mode.add_argument('--front-manifest',type=Path,help='Use the page and anchor list for another user-designated sample.')
 a=p.parse_args()
 manifest=json.loads(a.front_manifest.read_text('utf-8-sig')) if a.front_manifest else None
 r=validate(*[json.loads(f.read_text('utf-8-sig')) for f in [a.details,a.raw,a.sheets]],template_only=a.template_only,front_manifest=manifest)
 out=json.dumps(r,ensure_ascii=False,indent=2)
 if a.output:a.output.write_text(out,'utf8')
 print(out);raise SystemExit(0 if r['passed'] else 1)
