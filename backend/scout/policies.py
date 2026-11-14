"""Source-specific admission. Business evidence is admitted according to its collection purpose."""
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


def describe_social_demand(title, raw, published_at=None, now=None):
    result = describe(title, raw, published_at, now)
    evidence = title + " " + re.sub(r"#[^#\n]*\[话题\]#", "", raw)
    topic = re.search(r"软件|系统|小程序|APP|ERP|MES|WMS|CRM|智能体|人工智能|信息化|数字化|自动化|AI", evidence, re.I)
    need = re.search(r"求推荐|求助|找.{0,12}(?:开发|团队|公司|外包|软件|系统)|寻.{0,10}(?:开发|合作|供应商)|需要.{0,20}(?:开发|系统|软件|智能体)|想.{0,12}(?:做|开发|搭建|改造)|有没有.{0,20}(?:推荐|团队|开发)|预算.{0,15}(?:做|开发)|(?<!需)求.{0,8}(?:开发|外包)", evidence, re.I)
    seller = re.search(r"承接|接单|接私活|接外包|欢迎咨询|源码出售|提供.{0,8}开发服务|专业.{0,8}开发团队|我们.{0,10}(?:擅长|专注)|教程|教学|课程推广|保姆级|干货分享|招聘|招人|应聘|求职|岗前实训|需要你.{0,5}加入|加入我们|转行|找工作|客户上门|专注.{0,15}定制开发|就找我们|开发报价|免费获取.{0,8}报价|寻找.{0,12}后端工程师|组建软件团队|我们有.{0,15}开发经验|主营业务|开发案例|自有.{0,12}团队|为您提供|满意.{0,8}付款|欢迎.{0,15}私信|欢迎私信|接.{0,8}(?:定制开发|软件开发|智能体开发)", evidence)
    guide = re.search(r"教程|全流程|收藏版|需要注意什么|开发指南|入门攻略|先要看这个|别先看|案例参考|客户定制的|终于交付|手搓一个", evidence)
    result.update(category="小红书需求", information_kind="demand" if topic and need and not seller and not guide else "bulletin")
    return result
