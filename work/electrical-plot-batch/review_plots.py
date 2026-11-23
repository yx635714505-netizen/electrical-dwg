"""整页及逐点试打核对，适用于 A3 满幅、未旋转的 1:100 模型视口。"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

PT_PER_MM = 72 / 25.4


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def font(size):
    path = pathlib.Path("C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def montage(items, columns, cell, file):
    if not items:
        return
    width, height = cell
    sheet = Image.new("RGB", (columns * width, math.ceil(len(items)/columns) * height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, thumb) in enumerate(items):
        x, y = index % columns * width, index // columns * height
        thumb.thumbnail((width - 10, height - 28), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x + (width - thumb.width)//2, y + 22))
        draw.text((x+4,y+2), label, fill="black", font=font(13))
    sheet.save(file)


def world_points(build, sheet):
    devices = [d for d in build.get("devices", []) if d.get("sheet") == sheet["number"]]
    for d in devices:
        xy = d.get("world")
        if not xy or len(xy) < 2:
            raise ValueError(f"{sheet['number']} {d.get('id',d.get('kind'))} 缺少出图模型坐标 world")
        yield d, xy


def collect_clips(page, sheet, build, destination, report):
    # Build.cs uses a full-bleed paper-space viewport at custom scale 0.01.
    x0,y0 = sheet.get("x",0),sheet["y"]
    width,height = page.get_size()
    if not (math.isclose(sheet["w"], 42000, abs_tol=.1) and math.isclose(sheet["h"], 29700, abs_tol=.1)):
        raise ValueError("请按本页实际视口变换核对设备位置")
    clips = []
    scale = 4
    page_w, page_h = math.ceil(width*scale), math.ceil(height*scale)
    for d, (x,y,*_) in world_points(build,sheet):
        cx = (x-x0) * PT_PER_MM / 100
        cy = (y-y0) * PT_PER_MM / 100
        if not (0 <= cx <= width and 0 <= cy <= height):
            raise ValueError(f"{d.get('id')} 的world坐标落在图框外")
        # PDFium takes crop distances from left,bottom,right,top in points.
        radius=38
        crop=(max(0,cx-radius),max(0,cy-radius),max(0,width-cx-radius),max(0,height-cy-radius))
        left,bottom,right,top = (math.ceil(d*scale) for d in crop)
        clips.append((d,(left,top,page_w-right,page_h-bottom)))
    if not clips:
        raise ValueError(f"{sheet['number']} 的 build.devices 未提供逐点清单")
    # Rasterize the union once. Integer margins preserve PDFium's crop alignment.
    left=min(b[0] for _,b in clips)
    top=min(b[1] for _,b in clips)
    right=max(b[2] for _,b in clips)
    bottom=max(b[3] for _,b in clips)
    margins=(left/scale,(page_h-bottom)/scale,(page_w-right)/scale,top/scale)
    bitmap=page.render(scale=scale,crop=margins)
    raster=bitmap.to_pil().convert("RGB")
    bitmap.close()
    items=[]
    for d,(x1,y1,x2,y2) in clips:
        image=raster.crop((x1-left,y1-top,x2-left,y2-top))
        pixels=np.array(image)
        blank=not np.any(pixels.min(axis=2)<175)
        if blank:
            report["errors"].append(f"{sheet['number']} {d.get('id',d['kind'])} 局部为空")
        items.append((f"{d.get('id','')} {d.get('ident','') or d['kind']} {d.get('room','')}",image))
    raster.close()
    for n in range(0,len(items),12):
        file=destination/f"{sheet['number']}_局部_{n//12+1:02}.png"
        montage(items[n:n+12],4,(315,335),file)
        report["crops"].append(file.name)
    return len(items)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=pathlib.Path)
    parser.add_argument("work",type=pathlib.Path)
    parser.add_argument("--build",type=pathlib.Path)
    parser.add_argument("--dest",type=pathlib.Path)
    args=parser.parse_args()
    build_file=args.build or next((p for p in [args.work/"build.json",args.work.parent/"generate/input/build.json"] if p.exists()),args.work/"build.json")
    build=read(build_file)
    destination=args.dest or args.work/"plot_qa"
    destination.mkdir(parents=True,exist_ok=True)
    report={"source":str(args.output.resolve()),"build":str(build_file.resolve()),"pages":[],"crops":[],"errors":[]}
    for mode,dirname in [("黑白","plots"),("彩色","color")]:
        thumbnails=[]
        for sheet in build["sheets"]:
            number=sheet["number"]
            file=args.output/dirname/(number+".pdf")
            entry={"mode":mode,"sheet":number,"file":str(file)}
            report["pages"].append(entry)
            try:
                if not file.is_file() or not file.stat().st_size:
                    raise ValueError("缺失或零字节")
                with pdfium.PdfDocument(file) as doc:
                    if len(doc)!=1:
                        raise ValueError(f"单张试打含 {len(doc)} 页")
                    page=doc[0]
                    try:
                        size=[v/PT_PER_MM for v in page.get_size()]
                        entry["size_mm"]=[round(v,2) for v in size]
                        if any(abs(v-dim)>0.6 for v,dim in zip(size,(420,297))):
                            raise ValueError(f"非A3横向，实测 {entry['size_mm']}")
                        bmp=page.render(scale=1)
                        img=bmp.to_pil().convert("RGB")
                        bmp.close()
                        a=np.array(img).astype(np.int16)
                        # Exclude the title block and frame when checking for content.
                        interior=a[int(.10*a.shape[0]):int(.82*a.shape[0]),int(.12*a.shape[1]):int(.86*a.shape[1])]
                        ink=(interior.min(axis=2)<205)
                        entry["interiorInkPixels"]=int(ink.sum())
                        entry["coloredPixels"]=int((a.max(axis=2)-a.min(axis=2)>35).sum())
                        if entry["interiorInkPixels"]<100:
                            raise ValueError("页面主要绘图区为空或仅零星像素")
                        if mode=="黑白" and entry["coloredPixels"]>100:
                            raise ValueError("黑白输出含明显彩色线条")
                        if mode=="彩色" and sheet["kind"]=="weak" and entry["coloredPixels"]<50:
                            raise ValueError("弱电彩色输出未检测到足量彩色线条")
                        img.thumbnail((370,275),Image.Resampling.LANCZOS)
                        thumbnails.append((f"{number} {sheet['name']}",img))
                        if mode=="彩色" and sheet["kind"] in ("weak","socket","lighting"):
                            entry["points"]=collect_clips(page,sheet,build,destination,report)
                    finally:
                        page.close()
            except Exception as e:
                report["errors"].append(f"{mode} {number}：{e}")
        montage(thumbnails,3,(380,298),destination/f"{mode}_总览.png")
    (destination/"试打核对.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"{len(report['pages'])}项试打检查，{len(report['crops'])}张局部拼图，{len(report['errors'])}项异常。{destination}")
    for error in report["errors"]:
        print(error)
    return 1 if report["errors"] else 0


if __name__=="__main__":
    sys.exit(main())
