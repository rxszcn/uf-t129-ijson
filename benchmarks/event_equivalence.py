"""普通长度文档：修复前后事件序列逐字等价校验。

覆盖测试套件内的标准 JSON 文档（test_base 的全部夹具），在多种缓冲尺寸下
比较修复前后 basic_parse 的完整事件序列，要求逐元素完全相等。
"""
import importlib.util
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tests'))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


old = load_module('_python_old_under_test', os.path.join(HERE, '_python_old.py'))
from ijson.backends import python as new  # noqa: E402
import test_base  # noqa: E402

# test_base 中所有 bytes 形式的 JSON 文档夹具
DOC_NAMES = [
    'JSON', 'ARRAY_JSON', 'SCALAR_JSON', 'STRINGS_JSON',
    'SURROGATE_PAIRS_JSON', 'EMBEDDED_NUL_JSON',
]
DOCS = [(name, getattr(test_base, name)) for name in DOC_NAMES]
# 追加多值文档
DOCS.append(('JSON_twice', test_base.JSON + test_base.JSON))

BUF_SIZES = [1, 2, 3, 4, 7, 16, 64, 256, 1024, 4096, 65536]


def events(backend, data, buf_size, multi=False):
    return list(backend.basic_parse(io.BytesIO(data), buf_size=buf_size,
                                    multiple_values=multi))


def main():
    failures = 0
    checked = 0
    for name, data in DOCS:
        multi = name == 'JSON_twice'
        for buf_size in BUF_SIZES:
            old_ev = events(old, data, buf_size, multi)
            new_ev = events(new, data, buf_size, multi)
            checked += 1
            if old_ev != new_ev:
                failures += 1
                print("MISMATCH doc=%s buf=%d" % (name, buf_size))
                for i, (o, n) in enumerate(zip(old_ev, new_ev)):
                    if o != n:
                        print("  first diff at", i, "old", o, "new", n)
                        break
                if len(old_ev) != len(new_ev):
                    print("  length old=%d new=%d" % (len(old_ev), len(new_ev)))
    print("documents=%d checks=%d failures=%d" % (len(DOCS), checked, failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
