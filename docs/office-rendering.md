# 本机 Word/WPS 导出

普通 DOCX 检测可选择通过本机应用只读导出 PDF，供页面复核和下载。检测规则仍读取原始 OOXML 属性，导出成功不等于格式通过，不凭 XML 段落序号推算 PDF 页码。

## 使用

Windows 服务主机需要安装 Word 或 WPS。三个系统都执行 `pip install -r requirements.txt`；其中 `pywin32` 只在 Windows 安装。macOS 和 Linux 会跳过它，导出能力保持不可用：

```powershell
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
```

新建检测选择 DOCX 后，展开“更多选项”，勾选“使用本机 Word / WPS 生成 PDF”。页面读取服务主机的能力状态；依赖缺失时显示原因并允许重新检查。配对 PDF 与普通检测的本机导出二选一。CLI 使用 `check` 的 `--render-word` 参数。学校外部专项引擎保留自身导出接口。

完成后从任务附件下载 `rendered/document.pdf`。报告中的 `rendered_document` 保存输入与输出 SHA256、COM 接口、应用报告的名称／版本以及实际进程可执行文件名，不保存本机安装路径。问题仍定位到真实原稿段落；页码、目录与视觉效果请对照导出文件。

## 执行约束

- 只有用户明确选择后才启动应用。能力探测仅读取注册信息，不启动 Word/WPS。
- 在有界 worker 中打开任务副本，禁用自动宏，按只读且不加入最近文件的方式打开；不保存输入。导出前后验证输入，PDF 不超过 40 MiB。
- 含宏、活动部件、外部关系、外部数据域、待导入内容或无效包关系的文档被拒绝；可自行处理后上传配对 PDF。内部书签链接和有效页码域可以保留。
- 通过临时空文档取得窗口对应 PID，确认是新建进程后才打开原稿；已有进程和用户文档不会被终止。已确认归属的进程交由 Windows Job Object 管理，超时／取消时随 worker 回收。
- 默认导出时限 90 秒，任务失败明确保留原因。生成的 PDF 与输入、报告摘要绑定，证据读取及附件交付继续校验哈希。
