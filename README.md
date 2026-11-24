# electrical-dwg

住宅电气天正 DWG 技能包。规则入口为 [SKILL.md](SKILL.md) 和 [当前规则索引](电气绘图当前规则索引.txt)。仓库收录原生样板、校准数据、出图与验收脚本，以及 Windows 后台 CAD 池源码。每个工程需要另行准备建筑和结构资料、楼层设计数据及该项目的原生 CAD 任务包。

## 服务器首次安装

服务器可通过 HTTPS 克隆公开仓库。以下 PowerShell 命令适用于新安装，目标目录应当为空。自定义了 Codex 技能目录时，相应替换目标路径。

```powershell
$skillDir = Join-Path $env:USERPROFILE '.codex/skills/electrical-dwg'
git clone https://github.com/yx635714505-netizen/electrical-dwg.git $skillDir
Set-Location $skillDir
git rev-parse --short HEAD
```

服务器按本机使用的 Windows x64、AutoCAD 2020 中文版和天正建筑 T20 V8 配置。先用运行任务的 Windows 账号完成 CAD 和天正的授权与首次启动，确认天正 Profile、DWT、字体和打印设备可用。后台池使用 Windows PowerShell 5.1 和 .NET Framework 4.x 的 x64 C# 编译器。其他 CAD 版本需重新核对原生对象兼容性。

在仓库根目录执行以下命令，使用 Python 3.12 环境，并为试打校核安装依赖。若 Python 已装在自定义位置，将 ELECTRICAL_PYTHON 指向该环境。

```powershell
python -m venv .venv
$env:ELECTRICAL_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
& $env:ELECTRICAL_PYTHON -m pip install numpy Pillow pypdfium2
& $env:ELECTRICAL_PYTHON work/electrical-plot-batch/review_preflight.py --help
Copy-Item cad_pool/config.json cad_pool/config.local.json
```

按服务器实际安装情况编辑 `cad_pool/config.local.json` 内的 acadExe、template、profileSource、registryProfiles。每台服务器配置一个共用池；已有池的机器应沿用其入口。新服务器配置好后，从仓库根目录运行：

```powershell
.\cad_pool\pool.ps1 -Action init
.\cad_pool\pool.ps1 -Action status
```

空闲的新池可用 `cad_pool/test_pool.ps1` 检查 CAD 启动、保存与独立回读。具体任务包、提交与启动方式见 [CAD 池说明](cad_pool/使用说明.md) 和 [审核稿复核](work/electrical-plot-batch/三项复核.md)。项目输入、输出及试打文件放在单独的项目目录。

## 样板与校准

在项目的样板副本目录中，按下表复制文件。运行 `review_preflight.py sockets <副本目录> <项目校准JSON>` 即可按文件内容核对校准依据。

| 仓库中的原件 | 校准脚本的副本名 |
| --- | --- |
| assets/front-directory-notes.dwg | legend.dwg |
| assets/front-systems.dwg | sample.dwg |
| assets/socket-legend-source.dwg | socket.dwg |

原件及抽取资源的来源、SHA-256 和用途见 references 目录内的三份 manifest。历史项目路径仅用于追溯。运行资源从当前克隆目录取得。

## 日后更新

当前定位和验收流程见 [V36 操作说明](references/placement-pipeline.md)，后台故障排查见 [CAD 池启动与续作](docs/CAD池启动与续作排查.md)。[定位规则形成记录](docs/history/placement/) 收录 V35 草案、情景验证、两版定位规则文本及 V36 实施计划和历史进度。归档文档中的任务指令、路径、通过数和项目证据均对应当时工作区。新项目请从 [Skill 入口](SKILL.md) 读取现行规则。

维护端在本仓库工作副本修改、验证、提交后执行 `git push origin main`。如果修改发生在另一份已安装的 Skill 或共用工作区，请先将对应变更同步到本仓库并检查差异。

服务器在 CAD 任务结束后，进入原克隆目录执行 `git pull --ff-only`。如果更新涉及池源码，待调度器停止后再执行 `pool.ps1 -Action init` 重新编译。服务器自有的配置、日志、任务目录及 Python 环境由 Git 忽略。
