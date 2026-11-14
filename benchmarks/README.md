# 长字符串跨块解析基准与对照

本目录用于复现和验证纯 Python 后端（`ijson.backends.python`）词法器在
**单条字符串字段跨多个 64KB 输入块**场景下的性能修复。

## 背景

修复前，`Lexer` 在一个字符串没有在当前缓冲内闭合时，会把新块拼到缓冲尾部，
然后从开引号位置重新搜索闭合引号。随着字符串变长，每来一块都把已扫描的前缀
重扫一遍，解析单条长字符串的耗时随长度呈**二次方**增长；同时 `buf += data`
在 CPython 下（unicode 扩容无过度分配）本身也是二次方拷贝。单块读入（缓冲
大于整份文档）不走这条跨块续读路径，耗时平坦，正好定位退化来源。

修复后词法器：

* 用分块列表累积续读数据，追加新块是 O(块大小) 而非 O(字符串大小)；
* 维护单调前进的块内游标，只在尚未扫描的内容里找引号，绝不从头重扫；
* 引号前反斜杠的奇偶判定可跨块回退，转义引号与词元边界语义保持不变；
* 仅在找到真正的闭合引号时物化一次完整词元。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `bench_long_string.py` | 长度递增（64KB→16MB）的耗时基准，输出修复前后对照、翻倍比、单块对照与吞吐，可 `--json` 落盘 |
| `long_string_results.json` | 最近一次完整基准的机器可读结果 |
| `diff_test.py` | 修复前后在随机分块/转义载荷下的逐事件差分测试 |
| `event_equivalence.py` | 普通长度标准文档在多种缓冲尺寸下的事件序列逐字等价校验 |
| `long_escape_correctness.py` | 兆级长字符串在块边界处的转义引号/反斜杠内容正确性校验 |
| `_python_old.py` | 修复前的后端源码（取自 `git HEAD`），仅供基准与差分对照加载，不参与打包 |

所有脚本都用 `python -I` 运行，避免当前目录的模块名遮蔽标准库。

## 复现步骤

```bash
# 完整长度递增基准（中位数，含保护性超时），结果写入 JSON
python -I benchmarks/bench_long_string.py --timeout 40 --json

# 自定义长度序列
python -I benchmarks/bench_long_string.py --sizes 65536,131072,524288

# 正确性：修复前后逐事件等价
python -I benchmarks/diff_test.py
python -I benchmarks/event_equivalence.py
python -I benchmarks/long_escape_correctness.py
```

## 如何读数

`bench_long_string.py` 的 `x2` 列是“长度翻倍时耗时的增长倍数”：

* 理想线性复杂度下该值趋近 **2**；
* 二次方复杂度下该值趋近 **4**。

实测（Python 3.12，64KB 分块，中位数）：旧实现 2MB 以上翻倍比稳定在
约 4，新实现稳定在约 2；16MB 字段处新实现耗时约为旧实现的 1/19，
且与“单块读入”同量级，证明跨块重扫退化已被消除。
