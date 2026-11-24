# V36 实墙扣洞口、独立几何校核与完整交付检查

本页是 V35 定位规则的执行链路，适用于新项目与修订版。专业要求仍读 [逐点定位验收](placement-verification.md) 及各专业参考。四个通用 Python 脚本均只读图纸数据；不启动 CAD、不改 DWG、不含项目坐标和固定数量。使用 Python 3 标准库。

## 1. 数据与生成顺序

1. 记录本次规则、建筑/结构原图与最终 DWG 的 SHA256。先检查建筑文件内部的全部图名、轴网与可用基础/结构图，确认其适用性；确实无结构依据时不生成基础接地页，并同步目录及验收页清单。未明确选型的容量与供电参数列技术待核。
2. 从原图独立导出墙柱、门窗洞口、门弧和家具洁具；关联实际对象句柄及变换。按源图独立编制 `expected.json` 的应设清单，再生成设计点位。不得从已画点位反推应设数。
3. 用 `build_geometry_inputs.py` 适配源几何。生成器调用 `placement_geometry.usable_spans()`：从真实墙/柱可见面扣除洞口和遮挡，设备整个安装边能落入的连续段才是候选。再按门弧、动线、台盆和床头柜等专业规则选点。不能先固定坐标，再以最近墙或墙外包框证明贴墙。
4. 最终 DWG 保存后，在加载天正的独立原生 Database 中重新打开读取，导出 `saved-native.json`。不要从生成器的坐标清单伪造回读。导出记录须来自该文件，包含实体、块内图元、实际变换、导出错误、文件哈希及单位。CAD 任务经共享池；任务执行结束与图纸验收通过分别记录。
5. 适配保存后实体；按实际句柄建立点位，补充 `requirement_id / room / physical_id` 等分类映射，不改写提取的安装边去迁就设计坐标。独立运行几何校核和其余验收，最后运行交付检查。旧生成器与项目打包脚本须接入此步骤，不能直接沿用旧 `passed=true`。

## 2. 原生几何适配契约

配置文件最小结构如下；数值只是接口示例，项目须从实际单位、图幅及原生样板读取：

```json
{
  "drawing_sha256": "最终DWG哈希",
  "source_drawings": {"architecture": "建筑DWG哈希"},
  "tolerance": 0.01,
  "floors": [{"id":"F1","region":[[0,0],[20000,20000]],"transform":[1,0,0,1,0,0]}],
  "sheets": [{"id":"电施-05","floor":"F1","region":[[0,0],[42000,29700]],"transform":[1,0,0,1,0,0]}],
  "profiles": [{"layer":"EQUIP-插座","block":"本样板实际块名","kind":"socket","extractor":"semicircle"}]
}
```

`region` 是原生数据中的本层/图幅范围，`transform=[a,b,c,d,tx,ty]` 把源图或图页映射到同一建筑坐标，`x'=a*x+c*y+tx`。各层和图页的映射独立核对，不能复制历史锚点。误差限值记录实际单位及取值依据，不当作施工净距。

源导出为实体数组，保留 `handle/type/bbox/grips`。当前适配范围：

- `TCH_WALL`：真实直墙起终点和中点夹点，加原生外包范围核实墙厚及偏心墙轴；输出两侧长墙面及墙体实体轮廓。仅有外包框、曲墙或不一致的夹点保持 `pending`。
- `TCH_OPENING`：由原生洞口端点匹配实际宿主墙，以墙厚扣洞口。门扇弧线的外包范围不能当洞口厚度。开启弧和操作侧仍在专门的操作空间检查中核对。
- `TCH_COLUMN`：使用 `visibleParts` 中闭合、无圆弧凸度的真实多段线外轮廓；同时作为遮挡体和候选柱面。没有实际轮廓时不拿柱外包框替代。固定装饰柱、柱脚柱帽等复杂构件需补齐各实际轮廓。
- 家具洁具等采用明确的 `role:"obstacle"` 和源对象闭合 `polygon`；纯注释块须明确 `role:"annotation"`。未分类的嵌套建筑/家具块与无法定位的相关实体保持待核。普通线段、图层名不会自动证明家具洁具识别完整，操作空间报告须核对该覆盖范围。
- 支承计算使用简单多边形；自交、退化数据拒绝。实体占位碰撞目前支持凸多边形；凹形、曲线轮廓须先按实际几何分解或补充专门核对证据，不能按凸包检查后当作通过。

最终原生导出结构为 `{"drawing_sha256":"...","errors":[],"blocks":{"*Model_Space":[...],"块名":[...]}}`。实体包含 `h/type/layer/bbox`；INSERT 增加 `block/pos/angle/scale`，角度为弧度。当前设备盘点识别 `EQUIP-` 前缀下全部非文字实体；其他设备图层须先按本项目明确归类并扩展适配及覆盖检查，不得直接遗漏。

原生符号配置：

- `semicircle`：ARC 有真实 `start/end/mid/sweep`，由半圆弦确定完整安装边和朝向，并保守包住半圆主体。处理嵌套、旋转、镜像和非等比变换；不是按插入点猜墙面。
- `reviewed-semicircle-chord`：仅用于已经审定的旧导出形状，要求同一原生块链中真实直径 LINE 与半圆 ARC 范围相符，并填写 `localTolerance`；不能作为任意块的外包框推断后备方案。
- `declared-native-edge`：填写经审定的原生 LINE 句柄 `primitive`、块内方向 `normal`，可用 `bodyPrimitive` 指向原生闭合直边 POLYLINE/LWPOLYLINE 轮廓。轮廓来自图元，不填目标坐标。缺完整主体轮廓、重复句柄无法唯一定位或无匹配样板，保持待核。

适配器保留所有设备实例；无匹配图页或符号配置也不能丢掉。图例、引注等如需排除，须在 `actual.exclusions` 逐实体记录 `handle/reason/evidence`。同一物理面板跨图表达用同一个 `physical_id`，各页的原生实例 ID 仍不同。

## 3. 命令与绑定文件

以下命令在项目独立控制目录执行，脚本从 Skill 的 `scripts/` 调用；`python` 替换为本机可用 Python 路径。输入配置与导出须按上节核实。

```powershell
$scripts = Join-Path $env:USERPROFILE '.codex/skills/electrical-dwg/scripts' # 自定义安装时改为克隆目录下的 scripts
python "$scripts/build_geometry_inputs.py" --source-native source-native.json --saved-native saved-native.json --config geometry-config.json --output normalized
python "$scripts/verify_placement.py" --source normalized/source-geometry.json --actual actual.json --manifest delivery-manifest.json --tolerance 0.01 --report geometry-report.json
python "$scripts/validate_delivery.py" --manifest delivery-manifest.json --report delivery-report.json
```

`normalized/actual-geometry.json` 加入本项目应设清单映射后保存为 `actual.json`。源几何文件保持原字节；若重新保存，重新计算其哈希及依赖报告。`source-geometry.provenance` 绑定源导出、配置和原图哈希；`actual` 绑定最终 DWG、原生导出和源几何哈希。报告用 `validate_delivery.bound_inputs(manifest_path)` 从实际文件计算 `inputs`，不在 `actual` 内嵌它自身的哈希，避免自引用。

清单所有文件引用都为 `{"path":"相对清单或绝对路径","sha256":"实际字节哈希"}`。`delivery-manifest.json` 必填：

| 字段 | 内容 |
|---|---|
| `schema / mode` | `1`；`review` 或 `construction` |
| `drawing` | 最终 DWG 引用 |
| `sources / rules` | 原图及本次实际执行规则的非空引用映射 |
| `readback / geometry_source / expected / actual` | 保存后原生导出、归一源几何、独立应设清单、实际实例清单 |
| `sheets` | 全套应交图号；按资料条件确定，不能删掉未验收页来通过 |
| `checks` | 下节七类报告的文件引用 |
| `engineering` | `status / items`；技术通过另需独立 `report` 引用 |

`expected` 必填 `basis:{源图ID:哈希}` 和 `requirements:[{id,sheet,floor,room,kind,quantity,basis}]`。数量依据源图床柜、洁具、设备和房间用途独立确定；`basis` 记录实际对象/规则。`actual.instances` 每个实例包含 `id,requirement_id,sheet,floor,room,kind,handles,mountingEdge,normal,footprint`。保存后原生实例、应设清单、验收记录三者分别比对；不预设项目数量。

## 4. 独立几何与整套交付检查

`verify_placement.py` 检查完整安装边与源墙面的连续支承、洞口/柱墙遮挡、所在侧方向、主体与障碍体占位、跨图实际安装边一致性及同墙同侧图形重叠。报告逐点列原生句柄、候选面、可用区间、失败原因及未支持项。墙段回归可调用 `support_only=True`，但该报告 `acceptanceEligible=false`，不可用于完整交付。

该脚本当前自动检查的是墙/柱面安装设备。吸顶灯的板底、楼梯安装标高等不属于二维贴墙算法支持范围，不能伪造墙安装边让其通过。它们须由对应的独立原生几何检查或逐点专业复核形成有依据的报告，与墙装设备结果合并为覆盖全部实际实例的 `geometry` 报告；保留各分项原报告引用及失败/待核项。未取得这部分证据时，整套几何保持待核，不能从实际清单里删掉灯具。

门弧操作侧、套间功能动线、床头柜对位、洁具避让、设备主体及高度冲突、控制端点和电气关系另行逐点核对。图面符号重叠不自动等同于不同安装高度的实体碰撞，须分别处理。

交付检查强制七类：`symbols`（原生图例）、`circuits`（回路/逐键控制/计算与物理管线路径）、`geometry`、`operation_and_clearance`（门侧动线/设备与净空）、`visual`、`presentation`（目录说明系统图、A3图框右栏及图名等）、`background`（洞口/轴网尺寸/固定装饰柱等保全及清理）。现有检查程序的实际结果按此汇总，不能只生成七个空的通过标题。

- 每份报告须含 `status, drawing_sha256, inputs, evidence`，错误保留在 `errors`；前五类还须按实际实例逐点给 `id,status,evidence`。不适用明确写理由，不能留空。几何必须是完整检查报告。
- `visual` 额外给 `artifacts` 图像引用、全套 `pages`、每点局部证据。每个页面和点位含 `evidence:{artifact,page:1,region:[左,上,右,下]}`，区域为相应 PNG 像素坐标。每页使用实际 A3 试打的非交错 8 位 PNG，局部指向本页有效范围。程序核对图像、哈希、页和区域有效性；图像内容与安装合理性仍须实际查看，不能用有效 PNG 文件代替看图。
- 原生代理实体、导出错误、应设与实际数量差、重复/漏画、缺报告、缺局部图、过期哈希，以及图上已知错误均阻止通过。改 DWG、规则或任一依据文件后，重新回读并重做依赖检查。
- `reviewDraftReady=true` 仅表示应核图面、定位和证据完整通过；设备未选型等真正技术待核可明确列在 `engineering.items`，不等同于施工批准。`constructionReady=true` 还要求技术待核为零和与当前文件哈希绑定的独立技术核定报告。已知工程错误标 `failed`，不可降为技术待核。
- 仅在所需模式脚本退出码为 0，且报告相应 Ready 为真时打包该 DWG。否则保留修正/待核清单，不能宣称完成。交付同时列实际各阶段时间、排队和重试；保留覆盖、报告及试打证据。

回归：在 Skill 的 `scripts` 目录运行 `python -m unittest discover -s tests -v`。测试是算法与交付门槛验证；项目自身的完整验收仍以最终 DWG、源图、独立清单及实际试打为依据。
