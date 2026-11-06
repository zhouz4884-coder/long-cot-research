# DEER作者状态机与PRo独立扩展：实现、边界和验收

版本：2026-10-14。主formal和M1十二方法不变。本组件解决强基线缺口，不能以它替代M1的实际结果。

## 已核对的对象

作者仓库 iie-ycx/DEER 固定commit `c9dd19fbffa27f841cfe47502d015b63811b4d1b`；Qwen文件SHA256 `96460df9d532e02ca82535f6b5a6757cffff40bcbb233a4d6a1bd074684cc095`。原文件不改。完整主状态机包括ATP分块、试答、置信拒绝后恢复Wait、继续、自然thinking结束、预算结束、最终答案重新生成及错误输出。

[正式ICLR论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8df90a1440ce782d1f5607b7a38f2531-Abstract-Conference.html)第5页Eq.5给PRo均值减MAD规则，N=4、alpha=1；第23页给四种诱导提示和greedy设置，已查看实际页面。提示的空格/换行采用该页字面转录并冻结；没有公开可执行的作者PRo提示模板可对照其原始字节。基础Qwen源码的第一提示另有Markdown星号，PRo扩展使用论文四提示，这个差异明确保留。

## 三种执行模式

| 模式 | 行为 | 必须使用的名称与限制 |
|---|---|---|
| raw_source | 执行原main，保留试答实际默认温度/seed、原置信helper及其错误 | 固定作者源码在声明兼容环境中的执行；不称原作者全部实验环境复现 |
| declared_greedy_identity_repair | 原main不改；明确试答T=0/seed42，按实际发出的token ID取概率，短/缺失/非有限试答归零并记录原因 | 声明的兼容修复，不隐藏原错误；保留源码跳过首token、包含terminal的计分范围 |
| paper_pro_declared_greedy | 原main不改；每个试答请求扩成四个实际提示，按上述Qwen修复计分并用mean−MAD；全部token和批调用时间计费 | 论文式PRo的独立Qwen适配；不是作者未发布PRo源码，也没有实现论文的特殊mask分支与主链重叠加速 |

PRo校正分数可以为负，例如[1,0,0,0]得到−.125；不裁剪成“正确率”，不认为它是统计风险证书。原main在通过试答后仍重新生成最终答案，组件保持该行为，不能叫“提交已检查的候选”。Gold不进入控制器：仅传problem_id/question，source所需answer字段用不可见于模型的ID占位符，完成输出后重新绑定原ID。重复题面不排除、不更改问题，通过唯一占位符修复原题面排序带来的输出身份歧义。

## 已有可验证结果

- 原始孤立helper的CPU控制发现：HF两步无内部token返回NaN；Qwen单terminal试答发生ZeroDivisionError；字典排列会改变原helper分数。它们是实现控制，不证明真实vLLM排列或任务错误发生率。
- 已检查固定镜像vLLM0.10.2源码，试答省略温度时实际默认T=1、seed=None。源码注释“greedy”不能代替参数。所有raw行为保持并记录。
- 原AST扫描没有直接Assign不等于属性不可写。实际抽取镜像的dataclass CompletionOutput在CPU构造后，logprobs替换成功；初始报告和纠正证据都保留。
- 本地23项CPU控制通过，包含直接执行原main的拒绝/Wait恢复/接受/最终重生成、自然结束、原错误、短试答修复、PRo两轮八试答、admission四试答、Gold拒绝、重复题面身份，以及GPU/阶段拒绝控制。模型后端为脚本响应，完全不是4B模型benchmark。

## 独立运行环境和调度

固定已有镜像ID `sha256:5791f8642d1b71d45d832e232250aeca6a9aeb99b89698dff3c1ca5eea7a9655`，vLLM0.10.2、Torch2.8.0+cu128、Transformers4.56.1。作者requirements的vLLM<=0.6.1与此不同，必须称声明兼容环境。镜像缺NLTK/joblib；已从官方PyPI下载NLTK3.9.1/joblib1.4.2通用wheel并独立验证官方SHA。安装只到新workbench/runtime_deps，不改变主formal .venv；没有下载NLTK语料。

部署入口 `scripts/deploy_deer_workbench.py` 先核对实际主机两GPU UUID和formal哈希，只上传新workbench；不同版本不覆盖。CPU容器使用runc、无GPU/网络、只读系统及固定资源限制，逐文件验证安装内容等于wheel，再执行真实镜像CPU控制。网络失败保留attempt阶段和异常，不重启任何采集。

GPU入口 `scripts/run_deer_author_batch.py`：preflight只读，不加载模型；admission/selection都要求完整M1的marker、分析范围和raw SHA，检查原调度flock、GPU index/UUID/活进程，并在加载vLLM前实际重新核对模型文件。admission用source no_thinking=1强制覆盖试答，不作为任务成绩。不能趁dev→selection或训练的短暂idle空档抢GPU。

## 时延和正式对照边界

该入口记录真实batch wall（含import/init/warmup/log/output）、每个底层调用的全部prompt IDs、生成IDs/logprobs和token数。批调用时间不是逐请求延迟或goodput，不能拿它直接比M1单请求wall。

作者原system/user角色、greedy、ATP字符串截断/重编码、total-budget×think_ratio、20-token试答、可变剩余final预算，与主SDPA/Thinking/boxed16384+answer192不同。因此这是另一个声明协议的完整source比较对象；后续仍须完成同协议受控DEER/PRo、匹配后端FULL与实际选择结果，不能用当前准备掩盖这些未完成项，也不能继承主风险证书。

## 下一步必须得到的证据

1. 网络恢复后核对原监督器和worker，同一formal源码/数据绑定仍成立；不把TCP超时视作进程退出。
2. 独立workbench传输SHA、离线依赖实际安装和镜像23项CPU结果。目前未完成这些远端步骤时不能称部署成功。
3. 完整M1以后才做新vLLM finite GPU准入，记录实际四试答、返回ID/LP身份、20-token触顶、原helper错误与最终响应。
4. 做完整selection和匹配协议/后端对照，区分真正算法收益、解码/reader预算差、batch/prefix缓存系统因素。原错误请求保留；任何新设置在校准/测试前冻结。
