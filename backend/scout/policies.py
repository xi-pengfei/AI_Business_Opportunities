"""Source-specific admission. Only public tender discovery is connected today."""
import re

from scout.quality import describe


def describe_public_tender(title, raw, published_at=None, now=None):
    result = describe(title, raw, published_at, now)
    # A footer linking to a tender section is not a procurement announcement.
    evidence = re.sub(r"招标公告及供应商注册|招标公告及供应商|招标公告查询|招标公告列表", "", title + " " + result["text"])
    notice = re.search(r"招标公告|采购公告|招标项目|采购项目|询价公告|询比采购|竞争性磋商|竞争性谈判|采购需求公告|采购意向", evidence)
    if result["information_kind"] != "opportunity" or not notice:
        result["information_kind"] = "bulletin"
    else:
        result["category"] = "招采公告"
    return result
