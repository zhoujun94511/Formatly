# 外部检测引擎接入

日常检测可直接选择预置方案，或在“学校要求”上传模板和说明、核对条款后保存方案。这两条流程使用 Formatly 自带的检测插件；正文、标题与分节参数可用[论文与报告排版插件](native-plugin.md)检查，无需外接。

“学校专项 · 外部引擎”（`school-specific`）另调用一套兼容的本地 Python 专项工具，仅支持毕业论文、实习报告的 DOCX；可附同一文档的 PDF。它不出现在规则方案列表里，接入完成后再从本页进入检测。它不是任意第三方软件的通用接口，也不代表上传学校模板后会自动安装专项工具。

## 1. 准备完整引擎

在**运行 Formatly 后端的机器**上准备可信的完整引擎包，保留其依赖和来源资料。目录结构为：

```text
工具目录/
  school-engine/                 引擎根目录，可自行命名
    scripts/
      run_audit.py               audit_one、write_summary 入口
      check_document.py
      ...                       引擎依赖的其他脚本
    configs/
      sources.json              规则原件路径与 SHA256
      vendor_lock.json          固定 vendor 文件与 SHA256
      thesis.yaml               论文规则
      intern.yaml               实习报告规则
      ...                       引擎需要的其他配置
    .venv/                      可选的独立 Python 环境
    ...                         来源原件及引擎需要的资源
  vendor/                       必须与引擎根目录同级
    ...                         vendor_lock.json 锁定的完整文件
```

`sources.json` 的每个来源有 `path`、`sha256`；相对路径基于引擎根目录，绝对路径必须在当前主机上有效。`vendor_lock.json` 的 `files` 映射相对 vendor 路径到 SHA256，`commits` 记录版本。不要通过重写哈希来跳过不匹配；应恢复对应版本并核对学校依据。

引擎解释器需具备 `python-docx`、`PyYAML`、`lxml`、`pdfplumber`、`Pillow`、`pydantic`、`rich`、`loguru`，以及该引擎声明的其他依赖。优先按引擎自己的锁定依赖安装；安装 Formatly 不会自动安装这套独立环境。Word 渲染还需 Windows、兼容的已安装排版应用及该引擎支持的 COM 环境。

此适配器没有自动下载或安装接口。缺少完整引擎包时，应使用预置方案或学校要求生成的方案；只有同名脚本、空配置或一份 YAML 都不足以完成接入。

## 2. 在主机检查并保存配置

以下为 PowerShell 示例，路径为占位示例，请替换为实际安装位置。使用启动 Formatly 的同一个 Python 环境：

```powershell
# 临时检查，不修改配置
python -m formatly engines check --root 'C:\Tools\school-engine' --python 'C:\Tools\school-engine\.venv\Scripts\python.exe'

# 全部检查通过后，才保存本机接入配置
python -m formatly engines configure --root 'C:\Tools\school-engine' --python 'C:\Tools\school-engine\.venv\Scripts\python.exe'

# 按保存的配置复查
python -m formatly engines check
```

macOS 和 Linux 把上面的解释器换成引擎虚拟环境里的 `.venv/bin/python`，数据目录同样通过 `--data-dir` 传入：

```bash
python -m formatly engines check --root '/opt/school-engine' --python '/opt/school-engine/.venv/bin/python'
python -m formatly engines configure --data-dir "$HOME/.local/share/formatly" --root '/opt/school-engine'
```

省略 `--python` 时，优先使用引擎的 `.venv/Scripts/python.exe` 或 `.venv/bin/python`，最后使用当前 Python。命令返回 JSON；检查可用的退出码是 0，不可用或参数错误为 2。失败的 `configure` 不覆盖已有配置。

配置保存在 Formatly 数据目录的 `integrations.json`，其中包含本机路径，请勿提交到仓库或公开分享。若服务使用自定义数据目录，所有命令都应传入相同的 `--data-dir`，例如：

```powershell
python -m formatly engines configure --data-dir 'C:\FormatlyData' --root 'C:\Tools\school-engine'
python app.py --data-dir 'C:\FormatlyData' --no-browser
```

配置优先级是：检查命令显式参数 → `FORMATLY_LEGACY_ROOT` / `FORMATLY_LEGACY_PYTHON` 环境变量 → 已保存的本机配置 → 同级 `graduation-format-audit` 默认发现。环境变量存在时会覆盖已保存配置；更换引擎时应先处理旧值。变量名仅作为运行配置标识，不是另一个 Python 包或命令入口。

也可完全使用环境变量：在同一个终端设置两个变量后运行 `python app.py`；PyCharm 则在运行配置的“环境变量”中设置。只修改终端变量不会改变已经启动的服务进程。

```powershell
$env:FORMATLY_LEGACY_ROOT = 'C:\Tools\school-engine'
$env:FORMATLY_LEGACY_PYTHON = 'C:\Tools\school-engine\.venv\Scripts\python.exe'
python app.py --no-browser
```

## 3. 验证并使用

1. 停止并重新启动使用同一数据目录的 Formatly 服务。
2. 打开“设置 → 运行环境 → 外部专项引擎”，点击“重新检查”。页面逐项展示文件、解释器、依赖、规则来源、vendor 和入口检查；只读结果不公开主机路径。
3. 选择“毕业论文”或“实习报告”，验证方案。通过后点击“使用此方案检测”，进入原稿上传页。
4. 上传 DOCX，选择对应文档类型和“学校专项 · 外部引擎”。需要版式检查时显式附同稿 PDF，或在具备条件时选择生成 PDF。启动后查看问题、未完成组件和报告附件，不能只看错误数量。

CLI 使用同一个方案和业务服务：

```powershell
python -m formatly profiles preflight school-specific --kind thesis --format docx
python -m formatly check --input 'C:\Documents\sample.docx' --profile school-specific --kind thesis
# 实习报告使用 --kind intern；本机排版应用验证可显式添加 --render-word
```

预检不会导入并执行引擎业务入口；它验证已知适配契约和资源条件。正式检测在隔离进程中执行，并再次校验来源、vendor、输入及实现完整性，600 秒超时后终止。引擎遗漏、不可用、失败或完整性异常会保留错误，不能被计为通过。`checked`、`screened` 只表示已执行检查；已知的摘要测量格式偏差保留为问题，原始组件状态不会被改写为通过。专项规则的适用学校、版本和材料范围仍须核对。

## 常见故障与撤销

| 失败阶段 | 处理方式 |
| --- | --- |
| 未找到引擎 / 必需文件缺失 | 指定完整引擎根目录，保留其他脚本、配置和来源原件 |
| Python 不存在或无法启动 | 指向当前主机有效的解释器；复制的虚拟环境不可用时按锁定依赖重新创建 |
| Python 依赖缺失 | 在所选引擎解释器中安装引擎要求的依赖，不要误装到另一个环境 |
| 原件校验失败 | 恢复 sources.json 对应版本的来源文件，核对路径和依据 |
| vendor 校验失败 | 恢复与 vendor_lock.json 一致的同级 vendor 目录 |
| 规则或入口不兼容 | 使用符合下方入口契约的完整引擎版本；任意工具不能只改名接入 |
| CLI 可用，网页仍不可用 | 确认服务与 CLI 的 Python、数据目录、环境变量相同，并重启服务 |
| 预检可用，执行未完成 | 查看任务中实际失败的组件；预检不代替业务执行、Word 渲染或准确率验收 |

```powershell
# 删除本机保存的专项配置，保留任务、规则和报告
python -m formatly engines clear
```

`clear` 不修改环境变量；仍有变量时它们继续生效。重启服务后重新检查。配置命令只在主机执行，网页不接受服务器路径、解释器路径或安装命令。

## 开发其他引擎

现有专项适配器调用的入口为：

```python
def audit_one(source, kind, output, sources, *, pdf, pair_status, render_word):
    ...  # 返回包含 issues、engines、完整性状态的 dict

def write_summary(reports, output, provenance):
    ...
```

这两个函数由 `scripts/run_audit.py` 提供；引擎还须遵守 `legacy_worker.py` 对来源、vendor、报告结构、组件状态和输入不变性的检查。兼容入口不等于自动确认其检测质量。

接入不同实现时，使用公开的 `formatly.plugins` Python entry point，按[示例插件](../examples/README.md#安装独立插件)实现 `probe`、`run` 以及插件结果协议，在 Formatly 的 Python 环境本地安装，再通过方案选择。插件与 HTTP、CLI 共用检测流水线；无需再提供一套 Web 页面或另一个任务系统。Pandoc 的文档转换、WPS 的排版能力都不能直接代替此检测协议。
