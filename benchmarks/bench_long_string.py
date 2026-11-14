"""长度递增基准：纯 python 后端长字符串跨块解析的优化前后对照。

复现压测场景：采集汇聚层按固定 64KB 分块喂入流式解析，单条字符串字段
长度从 KB 级增长到兆级。脚本分别用修复前（git HEAD 中的原始 Lexer）与
修复后（当前 ijson.backends.python）实现解析同一份数据，输出：

  * 每个长度下两实现的耗时与翻倍比（长度翻倍时耗时增长倍数，线性≈2，
    二次方≈4）；
  * 单块读入（buf_size 大于文档）的对照读数，用于证明退化只来自跨块续读；
  * 吞吐 MB/s。

旧实现是二次方复杂度，长度过大时会非常慢，因此对每个长度设了保护性
超时（--timeout，秒）。被超时跳过的单元在输出中标记为 TIMEOUT。

用法：
    python -I benchmarks/bench_long_string.py
    python -I benchmarks/bench_long_string.py --json          # 同时写 JSON
    python -I benchmarks/bench_long_string.py --sizes 65536,131072
"""
import argparse
import importlib.util
import io
import json as json_mod
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHUNK = 64 * 1024


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


old = load_module('_python_old_under_test', os.path.join(HERE, '_python_old.py'))
from ijson.backends import python as new  # noqa: E402


def timed_run(backend, data, buf_size, timeout, repeat=3):
    """重复测量取中位数，返回 (中位耗时秒, 状态)。状态为 ok 或 timeout。

    用线程执行以便对二次方的旧实现施加保护性超时；任一轮超时即记为
    timeout，避免旧实现把整轮基准拖死。
    """
    import threading

    def once():
        t0 = time.perf_counter()
        for _ in backend.basic_parse(io.BytesIO(data), buf_size=buf_size):
            pass
        return time.perf_counter() - t0

    samples = []
    for _ in range(repeat):
        result = {}

        def worker():
            result['elapsed'] = once()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return None, 'timeout'
        samples.append(result['elapsed'])
    samples.sort()
    return samples[len(samples) // 2], 'ok'


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return '%.1f%s' % (n, unit) if unit != 'B' else '%dB' % n
        n /= 1024.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes',
                    help='逗号分隔的字符串内容长度（字节），默认内置递增序列')
    ap.add_argument('--buf-size', type=int, default=CHUNK,
                    help='流式分块大小，默认 64KB')
    ap.add_argument('--timeout', type=float, default=20.0,
                    help='单个测量单元的保护性超时秒数，默认 20')
    ap.add_argument('--json', dest='as_json', action='store_true',
                    help='把结果同时写入 benchmarks/long_string_results.json')
    args = ap.parse_args()

    if args.sizes:
        sizes = [int(x) for x in args.sizes.split(',')]
    else:
        # 长度递增：64KB -> 16MB，每级翻倍
        sizes = [CHUNK * (2 ** i) for i in range(0, 9)]

    rows = []
    header = (
        "str_len   readable   chunked_old   x2   chunked_new   x2   "
        "single_new   new_MB/s   old_status"
    )
    print(header)
    prev_old = prev_new = None
    for length in sizes:
        # 单条大字符串字段，外层是一个 object
        data = b'{"big_text": "' + b'a' * length + b'"}'
        doc_len = len(data)

        old_t, old_status = timed_run(old, data, args.buf_size, args.timeout)
        new_t, new_status = timed_run(new, data, args.buf_size, args.timeout)
        # 单块对照：缓冲大于整份文档，不触发跨块续读
        single_t, single_status = timed_run(new, data, doc_len + 16,
                                            args.timeout)

        def ratio(cur, prev):
            return ('  %.2f' % (cur / prev)) if (cur and prev) else '   - '

        old_cell = ('%.4fs' % old_t) if old_t else 'TIMEOUT'
        new_cell = ('%.4fs' % new_t) if new_t else 'TIMEOUT'
        single_cell = ('%.4fs' % single_t) if single_t else 'TIMEOUT'
        mbps = ('%.1f' % (doc_len / 1024.0 / 1024.0 / new_t)) if new_t else '-'
        print("%9d %9s %13s %s %13s %s %13s %9s   %s" % (
            length, human(length), old_cell, ratio(old_t, prev_old),
            new_cell, ratio(new_t, prev_new), single_cell, mbps, old_status))

        rows.append({
            'string_length': length,
            'document_bytes': doc_len,
            'buf_size': args.buf_size,
            'chunked_old_seconds': old_t,
            'chunked_new_seconds': new_t,
            'single_block_new_seconds': single_t,
            'old_status': old_status,
            'new_status': new_status,
            'single_status': single_status,
            'new_throughput_mb_per_s': (doc_len / 1024.0 / 1024.0 / new_t)
            if new_t else None,
        })
        prev_old = old_t or prev_old
        prev_new = new_t or prev_new

    if args.as_json:
        out = os.path.join(HERE, 'long_string_results.json')
        with open(out, 'w', encoding='utf-8') as f:
            json_mod.dump(rows, f, indent=2, ensure_ascii=False)
        print("\nwrote", out)

    # 退出码：新实现必须全部成功，否则视为回归
    return 0 if all(r['new_status'] == 'ok' and r['single_status'] == 'ok'
                    for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
