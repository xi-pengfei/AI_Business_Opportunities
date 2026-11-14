"""Conservative, evidence-based cleanup; source documents are never rewritten."""
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

ZONE = timezone(timedelta(hours=8))
DATE = r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?"
PROVINCES = "北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆 台湾 香港 澳门".split()
PLACEHOLDERS = re.compile(r"no information is available|cannot provide a description|暂无(?:内容|简介)|请开启javascript", re.I)
NAV = r"首页|当前位置|网站首页|联系我们|关于我们|返回顶部|登录|注册|收藏文章|打印文章|网站地图|帮助中心"


def as_date(value):
    if not value:
        return None
    match = re.search(DATE, str(value))
    try:
        if match:
            return datetime(*map(int, match.groups()), tzinfo=ZONE)
        return parsedate_to_datetime(str(value)).astimezone(ZONE)
    except (ValueError, TypeError, OverflowError):
        return None


def describe(title, raw, published_at=None, now=None):
    now = now or datetime.now(ZONE)
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    plain = soup.get_text("\n")
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", plain)
    plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"[\r\t]+", " ", plain)
    original = " ".join(plain.split())
    published = as_date(published_at)
    if not published:
        match = re.search(r"(?:发布日期|发布时间|发布于|更新时间|发布时间为)[：:\s]*" + DATE, original)
        if not match:
            match = re.match(r"\s*" + DATE, original)
        if match:
            published = as_date(match.group())
    procurement = bool(re.search(r"招标|采购|投标|询价|磋商", title))
    reason = freshness_reason(published, now)
    if PLACEHOLDERS.search(original) or not original.strip() or original.strip() == title.strip():
        reason = "missing_summary"
    deadline = re.search(r"(?:投标截止时间|响应文件提交截止时间|开标时间)[：:\s]*" + DATE, original)
    if procurement and deadline and as_date(deadline.group()):
        if as_date(deadline.group()).date() < now.date():
            reason = "expired_deadline"
    notice_years = [int(y) for y in re.findall(r"20\d{2}", title)]
    if re.search(r"公示|通知|申报|拟认定|拟支持|资金支持|奖补|补助|名单", title) and notice_years and max(notice_years) < now.year:
        reason = "historical_notice"
    # Only explicitly labelled geography or a province at the beginning of a title.
    region = evidence = None
    marker = re.search(r"(?:项目地区|项目所在地|项目地址|实施地点|建设地点|交货地点)[：:\s]+([^。；;\n]{2,70})", plain)
    candidates = [marker.group(1)] if marker else []
    candidates.append(re.sub(r"^[【\[（(\s]+", "", title))
    for candidate in candidates:
        matches = [p for p in PROVINCES if candidate.startswith(p)]
        if len(matches) == 1:
            region, evidence = matches[0], candidate[:100]
            break
    # Remove boilerplate/navigation, preserving substantive sentences and original evidence.
    plain = re.sub(r"当前位置[^\n。]{0,180}(?:\n|。|$)", "\n", plain)
    plain = re.sub(r"(?:发布日期|发布时间|更新时间)[：:\s]*" + DATE + r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", "", plain)
    lines = []
    for part in re.split(r"[\n]+|(?<=[。！？])", plain):
        part = re.sub(r"^[#*\s>|·]+", "", part).strip()
        if re.match(r"(?:上一篇|下一篇|相关阅读|相关推荐|版权|备案号|联系人及电话)", part):
            continue
        if len(part) < 2 or re.fullmatch(r"(?:" + NAV + r"|[\s>›/|·-])+", part):
            continue
        if len(re.findall(NAV, part)) >= 3:
            continue
        part = re.sub(r"^(?:首页|当前位置)[：:\s>›/|]*", "", part)
        if part not in lines:
            lines.append(part)
    useful = [s for s in lines if re.search(r"需求|采购|招标|建设|系统|信息化|智能|招聘|融资|项目|服务", s)]
    summary = " ".join((useful or lines)[:3])[:360].strip()
    if not summary and not reason:
        reason = "missing_summary"
    fragments = source_fragments(raw)
    if not fragments and not reason:
        reason = "missing_fragment"
    return {"text": summary, "fragments": fragments,
            "category": information_category(title, raw), "information_kind": information_kind(title, summary), "quality_status": "archived" if reason else "active",
            "quality_reason": reason, "region": region, "region_evidence": evidence,
            "published_at": published.date().isoformat() if published else None}


def source_fragments(raw):
    """Return literal spans plus offsets in normalized source text; never paraphrase."""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    source = " ".join(soup.get_text(" ").split())
    fragments = []
    keywords = re.compile(r"ERP|MES|AI|智能体|信息化|数字化|采购|招标|需求|招聘|融资|扩建|建设|供应商|审批|对账|系统|软件", re.I)
    has_keyword = keywords.search(source)
    for match in re.finditer(r"[^。！？；;\n]+[。！？；;]?", source):
        value = match.group()
        hit = keywords.search(value)
        if (not hit and has_keyword) or len(value.strip()) < 8 or PLACEHOLDERS.search(value):
            continue
        if re.search(NAV + r"|招标搜索|带附件搜索|加载中|版权|备案号", value) or value.count(">") >= 2:
            continue
        # Take one contiguous source span, including no more than 80 characters.
        left = max(0, hit.start() - 20) if hit else 0
        start = match.start() + left
        end = min(match.end(), start + 80)
        while start < end and source[start].isspace():
            start += 1
        while end > start and source[end - 1].isspace():
            end -= 1
        text = source[start:end]
        if not text or any(f["text"] == text for f in fragments):
            continue
        fragments.append({"index": len(fragments), "text": text, "start": start, "end": end,
                          "before": source[max(0, start - 45):start],
                          "after": source[end:end + 45]})
        if len(fragments) == 3:
            break
    return fragments


def information_category(title, raw):
    if re.search(r"招聘|岗位职责|任职要求", title + " " + raw[:1000]):
        return "招聘动态"
    if re.search(r"招标|采购|投标|询价|磋商", title):
        return "招采公告"
    if re.search(r"需求|寻找|求助|求推荐", title):
        return "需求讨论"
    if re.search(r"融资|扩建|投产|新闻|动态|财报|年报", title):
        return "企业动态"
    return "其他信息"


def freshness_reason(published, now):
    # Date-only source evidence uses Shanghai civil days, not capture time.
    if published is None:
        return "unverified_date"
    if published.date() > now.date():
        return "future_publication"
    if published.date() < (now - timedelta(days=30)).date():
        return "outside_30_days"
    return None


def information_kind(title, text):
    """Conservative routing, not a claim that a lead has been verified."""
    evidence = title + " " + text
    if re.search(r"政策|指导意见|实施意见|管理办法|工作报告|解读|名单公示|新闻|报道|中标|成交|终止|废标|关于印发|行动方案|实施方案|采购异常", title):
        return "bulletin"
    if re.search(r"采购异常|招标异常|终止公告|废标公告|成交公告|中标结果", evidence):
        return "bulletin"
    buyer = re.search(r"公司|集团|工厂|医院|大学|学院|学校|委员会|管理局|人民政府|采购人|采购单位|招标人", evidence)
    demand = re.search(r"采购公告|招标公告|招标项目|竞争性磋商|询价公告|采购需求|拟采购|计划采购|寻求.{0,16}(?:供应商|开发)|需要.{0,16}(?:系统|软件)|建设.{0,16}(?:系统|平台)", evidence)
    relevant = re.search(r"系统|软件|信息化|数字化|数智|人工智能|智能体|ERP|MES|WMS|AI", evidence, re.I)
    if buyer and demand and relevant and not re.search(r"招聘|岗位职责|供应商介绍|产品介绍|解决方案推荐", title):
        return "opportunity"
    return "bulletin"
