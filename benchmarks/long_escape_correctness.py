"""长字符串 + 跨块转义的内容正确性验证。

在兆级字符串中插入转义引号与不同数量的反斜杠，并刻意让这些转义序列落在
64KB 块边界两侧，验证修复后解析出的内容与 json 标准库完全一致。
"""
import io
import json

from ijson.backends import python as new

CHUNK = 64 * 1024


def parse(data, buf_size):
    return [v for e, v in new.basic_parse(io.BytesIO(data), buf_size=buf_size)]


def case(label, text, buf_sizes):
    data = json.dumps({'s': text}, ensure_ascii=False).encode('utf-8')
    expected = json.loads(data.decode('utf-8'))['s']
    for bs in buf_sizes:
        # 事件序列: start_map, map_key('s'), string(<值>), end_map
        string_events = [v for e, v in
                         new.basic_parse(io.BytesIO(data), buf_size=bs)
                         if e == 'string']
        assert len(string_events) == 1, (label, bs, len(string_events))
        got = string_events[0]
        assert got == expected, (label, bs, len(got), len(expected))
    print("ok: %s (len=%d)" % (label, len(text)))


def main():
    pad = 'a' * (CHUNK - 10)  # 让后续转义贴近 64KB 边界
    # 转义引号正好骑在块边界上
    case('escaped-quote near boundary', pad + '\"tail',
         [CHUNK, CHUNK - 1, CHUNK + 1, 4096])
    # 奇数个反斜杠 + 引号：引号被转义
    case('odd-backslashes escaped quote', pad + '\\\\' * 3 + '\"x',
         [CHUNK, CHUNK - 1, CHUNK - 2, 7])
    # 偶数个反斜杠 + 引号：引号是真正的结束符（其后再补内容）
    case('even-backslashes real quote', pad + '\\\\' * 4 + 'y',
         [CHUNK, CHUNK - 1, CHUNK - 3, 16])
    # 长串中周期性插入转义引号，覆盖大量跨块重扫点
    big = ('x' * 1000 + '\\"') * 2000
    case('periodic escaped quotes', big, [CHUNK, 4096, 1024, 64])
    # 纯反斜杠长串（偶数，合法）骑边界
    bs_text = '\\\\' * (CHUNK // 2 + 3)
    case('long backslash run', bs_text, [CHUNK, CHUNK - 1, 3, 64])
    print("all long-escape cases passed")


if __name__ == '__main__':
    main()
