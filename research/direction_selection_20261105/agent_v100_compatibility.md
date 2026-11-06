# V100 上的 Qwen3-4B 检查点干预：兼容性与容量审查

审查日期：2026-11-05。状态：**本地记录和官方资料审查；尚无本报告作者执行的 V100 推理测量**。

结论：V100 可作为错误前缀残留机制小实验的候选资源。应先用单卡、FP16、Transformers eager、串行分支、2k 前缀进行实际验收。不能把 3090 的 BF16、FlashAttention、KV 文件、激活或已有数值结果直接迁成 V100 结果。另有比 SM70 更早的门槛：若计算节点沿用 CentOS 7 的 glibc 2.17，则 torch 2.8.0+cu126 官方 Linux 轮子不可原生使用。

## 1. 本次证据与未确认项

- 只读取了本地 `D:/ACL/research/long_cot_landscape_20261105` 的模块评估和阅读札记，以及 `D:/ACL/experiments/radar20261013/provenance/qwen3_4b_verified.json`；没有改动冻结协议。
- 没有 SSH、作业提交、平台软件安装、模型权重下载或凭据处理。本报告中的安装/下载/验收代码均为准备方案。
- 主任务另行反馈的实测为：manager 是 Linux 3.10.0-957.el7.x86_64、glibc 2.17、Python 3.6.8，Torque 6.1.1；gpu2 同为 Linux 3.10.el7，节点报告 **8×Tesla V100-PCIE-32GB、driver 530.30.02**。八卡数量来自该节点报告，不是对“V100 平台”的一般假定；本报告作者没有独立登录复核。compute 的实际 glibc/Python 仍须按实际执行环境确认。
- **gpu2 当前不可直接使用**：主任务报告 gpu2 为 `job-exclusive`，36 个 CPU core 均已分配给既有作业；用户当前无自己的作业。GPU 显存近空不代表获得调度分配。应等待合法分配后再做 smoke；本报告不建议绕过 PBS 运行。`/data/apps` 存在 anaconda3、python3.11、glibc2.28、singularity 等目录，也不等于这些组件已适配 GPU 作业。
- **补充节点快照，接收/记录于 2026-11-05 17:56 HKT（09:56 UTC）**：主任务另实测 gpu1，报告 4×同型号 V100-PCIE-32GB，PBS `state=free`；gpu2 仍暂独占。主任务正按正常调度争取 gpu1 小规模 slot。此处 `free` 是当时的调度快照，不是持续可用保证，也不表示已分配或已通过模型/环境验收；模型缓存与环境路径仍在核查。
- 本次实际访问了官方 Hugging Face 的固定版本 config、index 和公开 LFS 元数据，未读取大权重文件。固定 HF revision 为 `1cfa9a7208912126459214e8b04321603b3df60c`。

## 2. 兼容性核对

| 项目 | 官方依据与判断 | 本实验处置 |
|---|---|---|
| GPU 架构 | NVIDIA 将 V100 列为 compute capability 7.0；Volta Tensor Core 的矩阵输入为 FP16，可使用 FP32 累加。 | 以 SM70 为实际运行门槛，单卡起步。见 [NVIDIA legacy GPU 列表](https://developer.nvidia.com/cuda/gpus/legacy)、[Volta tuning guide](https://docs.nvidia.com/cuda/archive/12.6.3/volta-tuning-guide/index.html)。 |
| BF16 | 原始 Qwen3-4B config 的 `torch_dtype` 为 `bfloat16`，不能让 `auto` 在 V100 上决定本实验 dtype。V100 无 Ampere 的原生 BF16 Tensor Core 路径；有些软件 BF16 检查可能把仿真实现也算作支持。 | 显式 `torch_dtype=torch.float16`；记录从 BF16 权重转换为 FP16 这一运行条件，检查非有限值。不得声称与 3090 BF16 数值等价。见 [固定版本 config](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/config.json)、[PyTorch BF16 检查源码](https://github.com/pytorch/pytorch/blob/v2.8.0/torch/cuda/__init__.py)。 |
| PyTorch CUDA 发行包 | PyTorch 版本号、CUDA toolkit 支持范围和轮子中实际编译的架构不是同一项证据。2.8 官方有 cu126 发行包；较新的 cu128/cu129 构建发生过 Volta 移除，不能对所有版本一概而论。 | 固定具体 wheel，现场确认 `torch.cuda.get_arch_list()` 含 `sm_70`，并实际执行 FP16 matmul/短推理。不能只看 `nvidia-smi` 的 CUDA 字样。见 [官方历史安装页](https://pytorch.org/get-started/previous-versions/)、[官方 Volta 构建变更讨论](https://github.com/pytorch/pytorch/issues/172352)、[get_arch_list 文档](https://docs.pytorch.org/docs/2.8/generated/torch.cuda.get_arch_list.html)。 |
| Linux glibc/C++ ABI | 官方 2.6 发布说明：cu126 已使用 manylinux 2.28 / CXX11_ABI=1；2.7 发布说明确认 Linux 全面迁移，CentOS 7 不再适配这类轮子。本次查询官方 cu126 index，2.8.0 CPython 3.10 x86_64 wheel 的文件名确实含 `manylinux_2_28`。 | **glibc 2.17 不能直接安装运行 2.8 cu126**。先核查计算节点 `getconf GNU_LIBC_VERSION`、Python、libstdc++ 和既有环境；选择下面的旧系统分支。见 [2.6 官方发布博客](https://pytorch.org/blog/pytorch2-6/)、[2.7 官方发布说明](https://github.com/pytorch/pytorch/releases/tag/v2.7.0)、[官方 cu126 包索引](https://download.pytorch.org/whl/cu126/torch/)。 |
| 驱动 | NVIDIA 表中的 CUDA 12.x Linux minor-compatibility 下限为 525.60.13；CUDA 12.6 GA 配套开发驱动为 560.28.03，后续 update 更高。二者用途不同；满足下限不等于所有 JIT/库路径均通过。CUDA 11.8 的 minor-compatibility 下限是 450.80.02。 | 依据计算节点实际驱动和实际 wheel 的运行验收选择 CUDA 包，不升级系统驱动来凑栈。见 [CUDA 12.6 release notes](https://docs.nvidia.com/cuda/archive/12.6.3/cuda-toolkit-release-notes/index.html)。 |
| FlashAttention | 官方 FlashAttention-2 CUDA 支持列出 Ampere/Ada/Hopper；FlashAttention-3 指向 Hopper。V100 不在该路径内。 | 不安装或强制开启 `flash_attention_2`；不沿用 3090 的 fused kernel 假设。见 [FlashAttention 官方 README](https://github.com/Dao-AILab/flash-attention#nvidia-cuda-support)。 |
| PyTorch SDPA | SDPA 包含 math 和多个融合后端，各有输入/硬件限制；math 后端对 half 输入保留 float 中间值。自动选择会影响数值和峰值显存。 | 机制基线优先 `eager`；SDPA 仅作固定后端的独立检查，必要时用 `sdpa_kernel(SDPBackend.MATH)`，不把 SDPA 自动选到某核当作 FA2 可用证据。见 [SDPA 官方文档](https://docs.pytorch.org/docs/2.8/generated/torch.nn.functional.scaled_dot_product_attention.html)。 |
| Transformers/Qwen3 | Qwen 官方模型卡指出 `<4.51.0` 会报 `KeyError: 'qwen3'`。4.55.2 已有原生 Qwen3 实现、eager 路由、KV cache 更新和 `logits_to_keep`。 | 候选固定 4.55.2；不需要远程自定义模型代码。使用原始 `Qwen/Qwen3-4B`，不替换为名称相近的 2507 Thinking/Instruct 版本。见 [Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3-4B)、[4.55.2 Qwen3 源码](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/models/qwen3/modeling_qwen3.py)。 |

## 3. 推荐最小栈：先按系统 ABI 分路

优先审计计算节点已经能够运行的独立环境，不把 manager 的包状态当作 gpu2 的状态。**2026-11-05 18:00 HKT 补充：主任务已发现既有 Python `/data/home/zhoubin/contractkv_v100/env/contractkv-v100-cu121/bin/python`，报告版本为 Python 3.10.6、torch 2.4.1、Transformers 4.55.2、ModelScope 1.38.1、safetensors 0.8.0、tokenizers 0.21.4。当前优先路线改为使用此环境做正常 PBS 分配下的 GPU 诊断，不先安装新包。** 目录名 cu121 不替代 `torch.version.cuda`、实际 build tag 和动态库加载结果；这些随诊断一起记录。以下安装方案保留为**现有环境失败后的备选**，不声称本次已运行成功。

### A. 若计算节点为 glibc 2.17 的原生旧系统

新建环境备选：Python 3.10、`torch==2.6.0` 的 **cu118 官方轮子**、`transformers==4.55.2`、FP16、eager、单 GPU。官方构建公告明确 2.6 的 Linux CPU/cu118/cu124 仍为 manylinux2014 / CXX11_ABI=0；cu126 已切换到 2.28。这里选 cu118，避免把“CUDA 12.x 总体可用”误当作老系统所有 CUDA 库均适配。主任务实测 driver 530.30.02 高于 CUDA 11.8 的最低要求；manager 自带 Python 3.6.8 不适合此栈，须使用独立且经 import 验收的 Python。见 [PyTorch 官方打包公告](https://dev-discuss.pytorch.org/t/pytorch-linux-wheels-switching-to-new-wheel-build-platform-manylinux-2-28-on-november-12-2024/2581)。

```sh
# 准备方案：仅在独立环境中执行，先取得计算节点规格与驱动。
python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu118
python -m pip install transformers==4.55.2 tokenizers==0.21.4 safetensors==0.6.2 numpy==1.26.4
```

本次从发布者 PyPI 元数据核实：`tokenizers 0.21.4` 和 `safetensors 0.6.2` 存在 x86_64 `manylinux_2_17` 轮子；仍须把全部实际解析的依赖、wheel SHA256、`pip check` 和 import 结果写入环境清单，不能让未固定的新依赖悄悄抬高 glibc 下限。见 [tokenizers 发布元数据](https://pypi.org/pypi/tokenizers/0.21.4/json)、[safetensors 发布元数据](https://pypi.org/pypi/safetensors/0.6.2/json)。

备选：如已有 `torch 2.5.1+cu121` 或 cu118 的可用环境，先进行同样的 ABI/SM70/FP16 smoke 验收，可作为实验候选，不必仅为版本号立即重建。Transformers 4.55.2 的导入门槛是 torch>=2.1；但其 `torch.load` 路径要求 torch>=2.6，**safetensors 不受这一加载版本限制**，故 2.5.1 路线显式 `use_safetensors=True`，禁止静默回退到 `.bin`。这只是兼容路线，不能代替实际加载验收。见 [Transformers 4.55.2 官方加载检查源码](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/utils/import_utils.py)。

### B. 若计算节点用户空间 glibc>=2.28

候选：Python 3.10/3.11、`torch==2.8.0` 官方 cu126、同一个 Transformers 4.55.2 与模型 manifest、FP16 eager。这样尽量减少与既有 3090 工作流的 PyTorch 主版本差异，但仍必须重新验收。当前 driver 530.30.02 对 cu126 属于 CUDA 12.x minor-compatibility 路线，低于 CUDA 12.6 GA 配套驱动；因此即便解决 glibc，也不优先把 cu126 作为平台首次运行路线。若平台已有受支持的容器运行时，可以把新 glibc 放入容器用户空间；容器不能替代宿主驱动/GPU 权限，也不能从 `/data/apps/singularity` 或 glibc2.28 目录存在推断它在 compute 上可用。本审查不建议修改宿主系统 glibc，或把新 loader 强行注入既有环境。

### 最少验收项目

在实际被调度到的 GPU 节点记录：节点/作业身份、系统 ABI、Python 路径、torch/Transformers/ModelScope 版本、驱动、CUDA runtime、`get_arch_list()`、device capability、总/空闲显存；执行 FP16 matmul 和 16–32 token 短推理并检查 finite。随后依次做同 token 前缀的全量重放/分块重放、同环境重复运行、1k→2k→4k 前缀的显存峰值测量。注意力干预前须有“无操作干预”和全重算控制。通过这些项目后才能把“资料兼容”更新为“实机可用”。

## 4. 按要求从 ModelScope 获取模型，并独立对齐 HF 身份

ModelScope 官方原始模型页面为 [Qwen/Qwen3-4B](https://modelscope.cn/models/Qwen/Qwen3-4B)。既有 `~/.cache/modelscope` 只是缓存根存在，不能证明权重完整、版本正确或计算节点能读取。

先沿用已发现的 ModelScope 1.38.1，记录实际接口和下载元数据，不因本报告而降级。旧版接口参照 `modelscope==1.29.2` 官方源码可查到 `snapshot_download` 的 `revision/cache_dir/local_dir/local_files_only`；**该旧版文档注明 revision 目前支持 branch/tag，这一限制不能未经核对直接套到 1.38.1；任何版本也不得把 HF commit 当作 ModelScope 的同义 revision**。应选择当前 SDK/ModelScope 可解析的版本，保存请求版本、服务端解析记录与全量文件内容哈希；如只能用可变 master，下载后冻结实际目录和 manifest，以内容身份约束实验。见 [ModelScope v1.29.2 官方接口参照](https://github.com/modelscope/modelscope/blob/v1.29.2/modelscope/hub/snapshot_download.py)。

```python
# 下载准备示例，未执行；使用新的模型工作目录，不覆盖既有缓存。
from modelscope import snapshot_download
model_dir = snapshot_download(
    "Qwen/Qwen3-4B",
    revision="master",  # 发现/解析用；实验身份由下载后的内容哈希冻结
    cache_dir="/path/to/approved/modelscope_cache",
)
# 以返回目录为准，不硬编码不同 SDK 版本的内部缓存层级。
```

校验分四层，任意一层失败都不能标为与旧模型相同：

1. **内容清单**：对 config、generation_config、tokenizer.json、tokenizer_config、merges、vocab、index 和所有三个 safetensors 分片逐文件计算字节数与 SHA256。拒绝缺失文件、HTML 错误页和 Git-LFS 文本指针；核对 index 每个引用的 shard 存在且 tensor 列表一致。
2. **HF 独立参照**：本地已有审计记录宣称上述十个文件与 HF revision `1cfa9a7208912126459214e8b04321603b3df60c` 全匹配。本次另向官方固定版本 endpoint 获取 config/index 和 LFS 元数据，确认 config/index 的 SHA256 和三个权重分片的 LFS SHA256 均与记录相同。HF 在这里仅提供参照元数据，模型仍按用户要求由 ModelScope 下载。参照是 [固定 config](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/config.json)、[固定 index](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/model.safetensors.index.json)、[固定 revision 公开元数据](https://huggingface.co/api/models/Qwen/Qwen3-4B/revision/1cfa9a7208912126459214e8b04321603b3df60c?blobs=true)。本次没有重哈希远端旧模型或下载 ModelScope 权重。
3. **Tokenizer 独立检查**：把 ModelScope 下载文件的哈希逐项与既有 manifest 对比；正式跨平台前再用官方固定 HF 小文件取得独立参照，或明确以经过审计的本地 manifest 为预先冻结参照。仅 config 相同不等于 tokenizer 相同。离线加载 tokenizer，检查词表大小、special-token ID、chat template、`enable_thinking` 和 Unicode/中英文/数学符号样例的编码；对既有轨迹直接比较完整 token-ID 数组，避免 decode→encode 改写空格/special tokens。
4. **运行身份**：`AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)`；模型使用同目录、`use_safetensors=True`、`local_files_only=True`、`torch_dtype=torch.float16`、`attn_implementation="eager"`。不要加载模型时重新联网解析 HF 名称，不要自动替换为新版模型。记录加载后实际参数 dtype 与 tensor 数量。

本次复核的关键参照：

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| config.json | 726 | `8ba006f74fecfaaeb392872a60f4a480e7ec9860153d2e1b769ec81f9a147f8a` |
| model.safetensors.index.json | 32,819 | `6dc0981b8829fead746441f68f38f24c5ca4a3a66351f652c26c6df0efc43ab2` |
| model-00001-of-00003.safetensors | 3,957,900,840 | `328a91d3122359d5547f9d79521205bc0a46e1f79a792dfe650e99fc2d651223` |
| model-00002-of-00003.safetensors | 3,987,450,520 | `6cd087b316306a68c562436b5492edbcf6e16c6dba3a1308279caa5a58e21ca5` |
| model-00003-of-00003.safetensors | 99,630,640 | `e4bf436957184f4eeb86a80e9db394503f1f56446b2e6b7edeac5b81470f4ca1` |

权重三行是本次核对的官方 LFS 对象标识与大小，**不是本次对 V100 本地文件进行内容哈希的结果**。

## 5. 2k/4k 前缀的保守显存规划：公式不是实测

固定 config 给出：36 层、32 个 Q heads、8 个 KV heads、head_dim=128，非 sliding-window。固定 index 的 `total_size=8,044,936,192` bytes，即约 7.492 GiB 的 16-bit 参数载荷；FP16 转换后的参数元素数相同。另有 CUDA context、分配器、激活、attention workspace、mask、logits 和加载瞬间副本。

单条序列的普通 FP16 KV：

`M_KV(S) = 2(K,V) × 36 × 8 × 128 × S × 2 bytes = 147456 × S bytes`。

| 长度 S | 单份 KV | eager 单层一张 FP16 H×S×S 矩阵 | FP32 同形矩阵 | 36 层完整 FP16 attention 输出同时保留 |
|---:|---:|---:|---:|---:|
| 2048 | 288 MiB = 0.28125 GiB | 256 MiB | 512 MiB | 9 GiB |
| 4096 | 576 MiB = 0.5625 GiB | 1 GiB | 2 GiB | 36 GiB |

这里 Q attention 用 **32 heads**，KV 用 **8 heads**，不能混用。4.55.2 eager 对 softmax 使用 FP32 再转换回 query dtype；计算时可能共存不止一张矩阵。若保留 FP32 attention，36 层下对应 18/72 GiB。故 16/32 GB V100 都不应全量保存 4k 的所有层所有 query attention；选择少量层/头/关键 query，逐层搬到 CPU 或在线只累计必要统计。见 [固定 eager 实现](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/models/qwen3/modeling_qwen3.py)。

令 B 为活动分支数，C 为额外保存的完整前缀 KV 数，T 为最大新增 token：

`规划显存 = 7.492 GiB + B×M_KV(S+T) + C×M_KV(S) + 工作区预留 + 其他开销预留 + 安全余量`。

不能默认 Python 引用/deepcopy 是共享前缀缓存；若分支各自复制，则每份额外 KV 都计入 C；若每个进程独立加载模型，参数项也要重复。以下人为预留不构成实际峰值上界：其他开销 2 GiB、安全余量 2 GiB；2k eager 工作区预留 2 GiB、4k 预留 6 GiB。设 B=1、C=1、T=512，得到约 **14.12 GiB / 18.69 GiB** 的容量规划值。

| 实际板卡情形 | 2k 前缀 | 4k 前缀 |
|---|---|---|
| 单张 V100 16 GB | 首选一个活动分支，串行比较；额外 KV 尽量移到 CPU；先测峰值再保留 GPU 快照。14.12 GiB 只是规划值。 | 上面的全量 eager 规划值超过容量；先用 256/512-token 分块 prefill、只输出必要 logits、无全层 attention 保留，实测通过后再使用。不能提前承诺可运行。 |
| 单张 V100 32 GB | 同样从单活动分支开始，较宽余量可容纳受控快照。 | 单活动分支和少量缓存具备容量候选条件；仍测真实峰值，不能把剩余容量换算成已经验证的并发数。 |

`T=512` 的单分支新增 KV 仅约 72 MiB；attention 的 S² 项和日志保留往往更值得防范。全序列 FP16 logits 本身在 2k/4k 约 0.580/1.159 GiB。生成或只查最后位置时使用固定实现的 `logits_to_keep=1`；做整段 teacher-forced 评分则分块计算并立即归约，不能把它当作只需最后 logits 的任务。分块 prefill 改变算子形状，须在实验内固定并通过同 token 重放控制，不能默认与全量 prefill 数值逐位相等。

## 6. 3090 轨迹可以重放，但不能继承数值状态

可携带的检查点是：精确 token IDs、题目/模板/消息结构、special-token 和 thinking 设置、位置/attention mask 约定、截断位置、模型文件 manifest、生成参数、标签/验证器输出以及样本与干预索引。使用同一模型内容和输入 ID，在 V100 上重新 teacher-force 前缀，生成该平台自己的 KV。

旧 GPU 的 KV、hidden activations、RNG 状态或 logits 可以作为来源明确的历史材料保存；**不能把搬运这些张量后得到的输出称为 V100 原生重放的数值结果**。即使张量能通过 CPU 序列化迁移，dtype、attention 后端、prefill 分块、PyTorch/CUDA 库、批大小和 GPU 架构仍会改变计算；BF16→FP16 更改变运行精度。PyTorch 官方明确不保证跨平台/版本逐位一致。应在每个平台分别建立 untreated/control/intervention 的配对比较，先测同环境重复差异，再报告跨平台差异。相同 seed 不能保证两个 GPU 上采样得到相同 continuation。见 [PyTorch numerical accuracy](https://docs.pytorch.org/docs/2.8/notes/numerical_accuracy.html)、[reproducibility](https://docs.pytorch.org/docs/2.8/notes/randomness.html)。

## 7. 与错误前缀残留机制小实验的接口

首轮不做大规模训练。以外部规则/可核验解证明某个中间断言为错、且随后已给相同纠正信息的前缀作为条件；“已知证伪状态”只是该断言的标签，不表示残留机制假设已经被证明。记录错误根断言、派生断言和后续复发的操作性定义。

| 干预 | 要保持/改变的对象 | 必需解释边界 |
|---|---|---|
| 文本纠正 | 原前缀后追加固定纠正文案 | 测的是纠正信息能否被承接；错误及派生内容仍在上下文中。 |
| 上下文替换/删除并重算 | 删除或替换指定 span 后从 token 重新构建 KV | token 数、位置变化本身是潜在混杂；加入等长替换、无关位置删改、同预算全重启。不能只删缓存里的错误根 token 并保留所有下游旧 KV 后声称状态干净。 |
| 注意力屏蔽 | 在明确层/查询范围阻断对错误 span 的直接读取 | 后续 token 的 KV 已可能间接编码该错误，屏蔽直接读取不等于清除污染。区分“仅 continuation 阶段屏蔽”和“从错误位置起重算时屏蔽”；固定相同 causal/position 约定。 |
| 无操作与随机位置控制 | 同代码路径但不改有效值；或相同数量随机/无关位置 | 排除 hook/mask 实现问题、单纯短上下文效应与更多计算效应。 |

注意力数值或可视化只是关联线索。机制结论至少要依赖可重复、位置特异、在相同输入和预算控制下的行为差异。优先报告修复后错误复发率、最终任务正确率、有害反转，以及真实 token/前向/重算成本；不同平台分别报告。若根位置干预和匹配随机干预同样有效，或者与全重做无差别，保留负结果，不升级为依赖恢复方法有效的结论。

更新后的推荐：**先在正常 PBS 分配内，用已发现的 Python 3.10.6 / torch 2.4.1 / Transformers 4.55.2 环境诊断，显式 safetensors、FP16 eager；不先安装新包。模型经 ModelScope 获取并逐文件对齐固定 HF manifest；单活动分支、2k 前缀、按需注意力统计、token 重放重建 KV。** 若现有环境验收失败，glibc 2.17 的新环境备选才是 torch 2.6.0 cu118；新 glibc 用户空间另可考虑 2.8 cu126。任何路线均以实际节点 smoke、模型哈希和显存峰值为准。

## 8. 已准备的 P0 合成接口集

同目录 `generate_p0_cases.py` 生成 `proposed_p0_cases.json`：16 个人工指定的整数变量依赖状态，其中 8 个旧分支确错且修订正确，4 个旧分支正确且复核不改值，4 个旧分支正确但带 `Wait` 的修订错误。每个状态仅有 x→y→z，文本保持短小，由主任务控制填充、字段可见性和模型模板。

生成器只用受限 AST 的整数加减乘及恰好整除，拒绝非整除和未定义变量；从原始定义独立计算正确值，再分别代入旧 x 与修订 x，验证终值、触发标签和组别条件。`oracle_trigger_label=1` 精确定义为“旧 x 与题目原始定义冲突”，不以 `Wait` 判断。标签、终值和组别显式列为 evaluator-only；`independent_conclusion` 是 privileged 的精确核验消息，不冒充模型诊断。

本地生成和重新读取检查均通过，组数为 8/4/4；JSON SHA256 为 `6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27`。检查命令：`python D:/ACL/research/direction_selection_20261105/generate_p0_cases.py --check-only`。这是 **teacher-forced 合成机理接口集，不是自然长 CoT benchmark**；未使用模型生成、Gold 筛选模型输出、GPU 推理或训练，未产生模型性能结论。

## 9. 对追加硬件“黄金分工”建议的证据评估

以下是官方资料能够支持的边界，不是本次训练或吞吐测量。平台环境事实来自主任务的当前实测反馈，本报告作者仍未 SSH 或运行 GPU。

### V100 不是“不能主训练”，FP16 也不能等同于 BF16

“V100 不能主训练”不成立为硬件定论。NVIDIA 官方说明 Volta Tensor Core 支持 FP16 混合精度训练，通常保留必要的 FP32 运算/权重更新状态，并通过 loss scaling 降低小梯度下溢问题。能否把某个任务的主训练放到 V100，仍取决于模型、优化器/激活内存、序列长度、软件后端和实测速率；当前选择先做机制 P0，是研究和资源决策。见 [NVIDIA 混合精度训练指南](https://docs.nvidia.com/deeplearning/performance/mixed-precision-training/index.html)。

V100 没有原生 BF16 Tensor Core 路线，因此不能直接沿用 3090 的 BF16 训练配置。FP16 数值范围更窄；loss scaling 主要处理梯度缩放，不把 FP16 的表示范围变成 BF16，也不能修复所有前向溢出。PyTorch AMP 官方特别指出 BF16 预训练模型可能超出 FP16 范围；本模型是否出现问题须检查 loss、梯度、激活非有限值与跳步比例，不能从一般 warning 推断本模型已经不稳定。见 [PyTorch AMP 的数值范围说明](https://docs.pytorch.org/docs/2.8/amp.html#gradient-scaling)。

### vLLM 的 V100 支持须固定版本与后端，当前栈不承诺直接可用

可验证的历史例子是 **vLLM 0.8.5**：官方安装页列出 compute capability>=7.0（包含 V100），支持模型页包含 Qwen3；但同版本源码对 CUDA capability<8 的设备不启用 V1，Volta 的注意力后端转到 XFormers。因此这是“特定版本的 V0/FP16/XFormers 路线具备官方支持证据”，不是“任意最新版 vLLM 可在 V100 直接安装”。见 [0.8.5 GPU 要求](https://docs.vllm.ai/en/v0.8.5/getting_started/installation/gpu.html)、[Qwen3 模型支持表](https://docs.vllm.ai/en/v0.8.5/models/supported_models.html)、[V1 架构门槛源码](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/engine/arg_utils.py)、[Volta 后端选择源码](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/platforms/cuda.py)。

0.8.5 的官方依赖明确固定 torch==2.6.0、xformers==0.0.29.post2；安装页还说明 CUDA/PyTorch 构建不同可能造成二进制不兼容，默认包是 CUDA 12.4。当前已有 torch 2.4.1 环境不能据此直接加装该 vLLM 包并宣称可用。旧 glibc、XFormers/自定义扩展 ABI、实际 SM70 kernel、530.30.02 对目标 CUDA 包的兼容路径均须另行验收；CUDA minor compatibility 下限不是这些依赖全通过的充分条件。本次 P0 保持 Transformers eager，不为吞吐提前改造推理引擎。见 [0.8.5 CUDA 依赖](https://github.com/vllm-project/vllm/blob/v0.8.5/requirements/cuda.txt) 与上述固定版本安装页。

### 八个独立 worker 的八倍，只是理想同卡参照

若八张卡均获分配、每卡独立装得下模型、任务可完全拆分且单卡速率相同，理想总吞吐才是单张**同型号、同栈**卡的八倍；这不等于相对 3090 八倍。实际完成时间还包含排队、模型加载/预热、数据传输、共享存储 I/O、任务长尾、合并和失败重试。容量为八张也不是调度保证，更不能用 gpu2 八张替代当前 gpu1 最多四张的节点资源事实。

可复核估算为 `总墙钟≈排队+初始化+max(worker运行时间)+汇总/I/O`；吞吐应以完成且通过验证的轨迹数或实际 token 数除以运行时间测得。若任务平均长度不同，应逐卡报告速率和尾部耗时。独立推理 worker 不必采用同步 DDP；如使用 DDP 训练，则另有梯度同步和慢 rank 等待。官方 DDP 文档明确它同步模型副本的梯度、按 GPU 分配独立进程；不能用 DDP 名称证明推理任务线性加速。见 [PyTorch 2.4 DDP 文档](https://docs.pytorch.org/docs/2.4/generated/torch.nn.parallel.DistributedDataParallel.html)。

### 两张 24 GB 不是统一的 48 GB，14B 的权重减法不是 KV 预算

2×24 GB 是两个独立设备的容量。数据并行通常各放模型副本；要容纳单卡放不下的模型，必须显式进行层/张量等模型切分或 offload，并分别满足每卡内存峰值、复制项和通信需求。它不会自动形成可任意分配的连续 48 GB 显存。分布式推理的官方实现也按每 GPU 一个 worker、每 worker 持有模型分片与 KV 描述。见 [vLLM worker 实现](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/worker/worker.py)。

即便用精确 14×10^9 参数作示例，BF16 权重载荷约 28×10^9 bytes（26.1 GiB）；实际名为 14B 的模型须按真实参数/权重清单计算，且 GB/GiB 不混用。“48−28=20 GB，全部可给 KV”漏掉了 CUDA context、激活峰值、通信/临时 buffer、mask/logits、分配器与安全余量，以及每卡切分不均衡。vLLM 的固定版本源码实际先做 profile，再从允许使用的设备内存中减去**全部非 KV 开销**，不是只减权重。这里“20 GB”至多是统一十进制且理想切分下的粗略剩余，绝非已验证 KV 容量。见同一 [官方内存 profile 与 KV 预算源码](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/worker/worker.py)。

### AWQ/GPTQ 会改变被干预的计算，须另立基线

AWQ/GPTQ 是权重量化方法，不能据其名称推断所有激活也变成低位。权重值、dequantization/kernel 路径和可能的 activation-aware 缩放均可能改变 hidden state、logits 和后续轨迹；这会影响激活替换/注意力干预的数值尺度及 hook 位置。应保存量化权重/配置/校准数据和后端身份，在量化模型内部重新做 untreated、无操作、配对干预；必要时把被比较的激活映射到同一数学位置。不能把 BF16 模型与 4-bit 模型的差别全部归因于干预方法。这个实验边界由量化改变权重计算推得，**不是 AWQ/GPTQ 原论文已经验证本项目激活干预等价**。见 [AWQ 原论文](https://arxiv.org/abs/2306.00978)、[GPTQ 原论文](https://arxiv.org/abs/2210.17323)。

硬件还须按实现区分：vLLM 0.8.5 的官方表对 Volta 标记 AWQ 不支持、GPTQ 支持、Marlin 不支持。因此“V100 直接用 AWQ/GPTQ 任一量化模型”也过强；更不能把 3090 上的 AWQ/Marlin 路线原样搬过来。见 [固定版本量化硬件表](https://docs.vllm.ai/en/v0.8.5/features/quantization/supported_hardware.html)。当前 P0 不引入量化，以免把模型变化与干预效应混在一起。

### “7B、8k–16k、1000–3000 样本，2–6 小时”目前不能保证

样本数不是充分工作量描述。即使每个样本恰有 8192–16384 个实际处理 token，1000–3000 样本的一轮遍历也已经是 **8.192M–49.152M token**；多 epoch、prompt/target 构造、padding/packing、筛选重采样、评估、训练方式（全参/LoRA）、batch/累积步数及 checkpointing 会继续改变工作量和速度。仅一轮遍历若要在 2–6 小时内完成，对应端到端处理速率约需 **379–6827 token/s** 的不同组合；这是由假定 token 数和时长相除得到的需求，绝不是平台测量值。训练处理吞吐也不能用自回归生成 token/s 代替。

可靠时间估算应先明确 batch/累积和尾部更新规则；在整数 epoch、无 packing、不丢尾部且 epoch 结束时提交剩余累积的简单情形，可规划 `更新步数≈epochs×ceil(样本数/有效全局batch)`，其他设置按真实 dataloader/训练器的 update 数计算。还应记录真实非 padding/实际计算 token、warmup 后 step time、前后向/重算成本、验证和保存时间。总时长另加排队、初始化和 I/O。未有代表性配置的短跑测量前，2–6 小时只能保留为待检验的预算假设；不能据此安排大规模训练或报告交付承诺。
