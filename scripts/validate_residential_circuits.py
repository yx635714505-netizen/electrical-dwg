"""Check residential branch grouping against the DWG build's device schedule."""
import argparse
from collections import Counter
import json
from pathlib import Path


MAX_TERMINAL_CIRCUITS = 10
LAMPS = {'LIGHT', 'WETLIGHT', 'WALLLIGHT'}
OUTLETS = {'SOCKET', 'AC', 'WET', 'HEATER', 'HOOD', 'BED'}


def outlet_group(device):
    if device.get('circuitPurpose'):
        return device['circuitPurpose']
    kind = device['kind']
    if kind in LAMPS:
        return 'light'
    if kind == 'HEATER':
        return 'heater'
    if kind == 'AC':
        return 'ac'
    if device.get('dedicatedUse') == '冰箱':
        return 'fridge'
    room = device.get('room', '')
    if '厨房' in room:
        return 'kitchen'
    if '卫' in room:
        return 'bath'
    return 'general'


def circuit_errors(circuits, devices):
    errors = []
    indexed = {circuit['id']: circuit for circuit in circuits}
    if len(indexed) != len(circuits):
        errors.append('配电回路号重复')

    terminal_counts = Counter(
        (circuit.get('unit'), circuit.get('panel') or circuit['id'].rpartition('-')[0]
         or f"第 {circuit['floor'] + 1} 层配电箱")
        for circuit in circuits if circuit['kind'] != 'feeder'
    )
    for (unit, panel), count in terminal_counts.items():
        if count > MAX_TERMINAL_CIRCUITS:
            name = f'{unit} {panel}' if unit else panel
            errors.append(f'{name} 末端回路 {count} 条，超过 {MAX_TERMINAL_CIRCUITS} 条上限')

    branches = Counter((c.get('unit'), c['floor']) for c in circuits if c['kind'] == 'light')
    served = set()
    assigned = Counter(point for circuit in circuits for point in circuit.get('points', []))
    known_power = {p['id']: p for p in devices if p['kind'] in LAMPS | OUTLETS or p.get('circuitPurpose')}
    if set(assigned) - {p['id'] for p in devices}:
        errors.append('回路台账含平面点位清单中不存在的点位')

    for device in known_power.values():
        key = device['id']
        circuit = indexed.get(device.get('circuit'))
        purpose = outlet_group(device)
        if purpose == 'light':
            unit = device.get('unit') or (circuit or {}).get('unit')
            served.add((unit, device['floor']))
        if not circuit or assigned[key] != 1 or key not in circuit.get('points', []):
            errors.append(f'{key} 未唯一归入一个回路')
            continue
        if purpose == 'light' and (circuit['kind'] != 'light' or circuit['floor'] != device['floor']):
            errors.append(f'{key} 未归入所属使用楼层的照明回路')

    for circuit in circuits:
        purposes = {outlet_group(known_power[key]) for key in circuit.get('points', []) if key in known_power}
        expected = circuit.get('groupPurpose')
        if len(purposes) > 1 or (expected and purposes and purposes != {expected}):
            errors.append(f"{circuit['id']} 的点位与回路用途不一致")

    for floor in served | branches.keys():
        if branches[floor] != 1:
            unit, level = floor
            prefix = f'{unit} ' if unit else ''
            errors.append(f'{prefix}第 {level + 1} 层应有一条普通照明支路，实际 {branches[floor]} 条')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    args = parser.parse_args()
    build = json.loads(args.build.read_text('utf-8-sig'))
    findings = circuit_errors(build['circuits'], build['devices'])
    print(json.dumps({'passed': not findings, 'errors': findings}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(findings))
