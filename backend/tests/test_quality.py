from datetime import datetime

from scout.quality import describe

NOW = datetime.fromisoformat("2026-11-14T12:00:00+08:00")


def test_dates_and_placeholders_are_filtered_but_source_dates_are_not_invented():
    result = describe("襄阳市系统招标公告", "发布日期：2024-11-22 16:58\n建设医院信息系统，采购软件服务。", now=NOW)
    assert result["quality_reason"] == "outside_30_days"
    assert result["published_at"] == "2024-11-22"
    assert "发布日期" not in result["text"]
    assert describe("大学招投标", "We cannot provide a description for this page right now.", now=NOW)["quality_status"] == "archived"
    unknown = describe("ERP建设需求", "计划升级ERP系统，对接供应商管理。", now=NOW)
    assert unknown["quality_reason"] == "unverified_date"
    assert unknown["published_at"] is None
    assert unknown["region"] is None


def test_summary_removes_navigation_and_region_requires_source_evidence():
    result = describe("信息化采购", "<nav>首页 联系我们 登录</nav><p>项目地区：四川 绵阳</p><p>采购MES系统，与现有ERP进行集成。</p>", now=NOW)
    assert "首页" not in result["text"]
    assert "MES" in result["text"]
    assert result["region"] == "四川"
    assert result["region_evidence"] == "四川 绵阳"
    assert describe("全国数字化采购", "供应商拥有北京、上海办公室，计划建设系统。", now=NOW)["region"] is None


def test_old_notice_stays_archived_even_with_future_deadline():
    title = "软件采购公告"
    active = describe(title, "发布日期：2026-01-01\n投标截止时间：2026-12-01\n采购ERP系统开发服务。", now=NOW)
    assert active["quality_reason"] == "outside_30_days"
    expired = describe(title, "发布日期：2026-11-01\n投标截止时间：2026-11-10\n采购ERP系统开发服务。", now=NOW)
    assert expired["quality_reason"] == "expired_deadline"
    # A report discussing past years is not an old tender notice.
    report = describe("企业2024年度回顾", "公司2024年完成一期建设，2026年计划开展智能化服务。", now=NOW)
    assert report["quality_reason"] == "unverified_date"


def test_expired_application_notice_is_not_current_demand():
    result = describe("2023年安徽省智能工厂名单公示", "根据申报规则，拟认定安徽企业的智能工厂。", now=NOW)
    assert result["quality_reason"] == "historical_notice"
    assert result["published_at"] is None


def test_fragments_are_literal_spans_with_reconstructible_context():
    from scout.quality import source_fragments

    raw = "负责业务调研。岗位职责包括：打通 ERP 与 MES 数据，建设统一的数据看板。具有制造业项目经验者优先。"
    parts = source_fragments(raw)
    assert len(parts) == 1
    part = parts[0]
    assert raw[part["start"]:part["end"]] == part["text"]
    assert part["before"] + part["text"] + part["after"] == raw
    assert "打通 ERP 与 MES" in part["text"]
    assert source_fragments("We cannot provide a description for this page.") == []


def test_navigation_is_never_carried_as_a_fragment_and_old_news_is_archived():
    from scout.quality import source_fragments

    assert source_fragments("招标网 > 招标搜索 > 信息化 > 招标公告 > 带附件搜索 加载中 招标项目") == []
    assert describe("企业数字化政策发布", "发布日期：2022-09-02。支持开展企业数字化建设。", now=NOW)["quality_reason"] == "outside_30_days"
