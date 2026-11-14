"""差分测试：修复前后 Lexer 在随机分块/转义场景下逐事件等价。

旧实现对长字符串是二次方复杂度，因此正确性对比统一使用小/中尺寸载荷；
长尺寸的近线性验证由 bench_long_string.py 单独完成。
"""
import importlib.util
import io
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


old = load_module('_python_old_under_test', os.path.join(HERE, '_python_old.py'))
from ijson.backends import python as new  # noqa: E402


def run(backend, data, buf_size):
    return list(backend.basic_parse(io.BytesIO(data), buf_size=buf_size))


def build_payload(seed):
    """构造保证合法、且富含转义/多字节内容的 JSON 字节串。"""
    rng = random.Random(seed)
    n = rng.randint(8, 20)
    values = []
    alphabet = 'abc .,-_xyz0123'
    for _ in range(n):
        chars = []
        for _ in range(rng.randint(0, 15)):
            choice = rng.randrange(5)
            if choice == 0:
                chars.append('\\')                      # 单反斜杠 -> JSON 中 \\
            elif choice == 1:
                chars.append('"')                       # 引号 -> JSON 中 \"
            elif choice == 2:
                chars.append(rng.choice(alphabet))
            elif choice == 3:
                chars.append('中文💩')                   # 多字节
            else:
                chars.append('\t\n')                    # 控制字符 -> \t \n
        values.append(''.join(chars))
    return json.dumps({'k': values}, ensure_ascii=False).encode('utf-8')


def compare(data, buf_sizes, failures, checked):
    for buf_size in buf_sizes:
        old_events = run(old, data, buf_size)
        new_events = run(new, data, buf_size)
        checked[0] += 1
        if old_events != new_events:
            failures.append((data, buf_size, old_events, new_events))


def main():
    failures = []
    checked = [0]
    all_sizes = [1, 2, 3, 4, 7, 16, 64, 256, 1024, 4096, 65536]
    for seed in range(120):
        data = build_payload(seed)
        # 极小缓冲仅用小载荷跑前 15 个种子，避免旧实现的二次方耗时
        sizes = all_sizes if seed < 15 else all_sizes[3:]
        compare(data, sizes, failures, checked)
        if len(failures) >= 5:
            break

    # 跨块反斜杠奇偶专项：内容层的反斜杠经 json.dumps 保证转义合法
    # k 个字面反斜杠 -> JSON 中 2k 个 '\'；再与转义引号组合覆盖奇偶边界
    special = [json.dumps({'a': '\\' * k}, ensure_ascii=False).encode('utf-8')
               for k in (1, 2, 3, 5, 8)]
    special += [json.dumps({'a': 'x' + '\\' * k + '"y'}, ensure_ascii=False).encode('utf-8')
                for k in (1, 2, 3, 5)]
    special += [json.dumps(s, ensure_ascii=False).encode('utf-8')
                for s in ('', '""', '\\"', '\\', '\\\\')]
    special += [b'["\\u0041\\n\\t"]']
    for data in special:
        compare(data, [1, 2, 3, 4, 7, 16, 64], failures, checked)

    # 中等尺寸长字符串：验证两实现结果一致（尺寸克制，旧实现仍可承受）
    for length in (1000, 4096, 20000):
        data = b'{"big": "' + b'a' * length + b'"}'
        compare(data, [4, 64, 4096], failures, checked)

    # 不完整字符串：两种实现都应抛 IncompleteJSONError
    import ijson
    for incomplete in (b'{"a": "abc', b'{"a": "abc\\', b'{"a": "abc\\\\'):
        for buf_size in (2, 64):
            for backend, label in ((old, 'old'), (new, 'new')):
                checked[0] += 1
                try:
                    run(backend, incomplete, buf_size)
                    failures.append((incomplete, buf_size, 'no error in ' + label, None))
                except ijson.IncompleteJSONError:
                    pass

    if failures:
        for data, buf_size, old_events, new_events in failures[:5]:
            print("MISMATCH buf=%d data=%r" % (buf_size, data[:80]))
            if isinstance(old_events, list):
                for o, n in zip(old_events, new_events):
                    if o != n:
                        print("  old:", o)
                        print("  new:", n)
                        break
    print("checked=%d failures=%d" % (checked[0], len(failures)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
