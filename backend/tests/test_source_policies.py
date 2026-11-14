from datetime import datetime

from scout.policies import describe_public_tender

NOW=datetime.fromisoformat('2026-11-15T12:00:00+08:00')


def policy(title,raw):
    return describe_public_tender(title,raw,'2026-11-10',NOW)


def test_company_news_is_not_a_public_discovery_opportunity():
    assert policy('公司要闻 - 中金岭南公司','公司扩产项目建设MES系统。联系我们 - 招标公告及供应商注册')['information_kind']=='bulletin'
    assert policy('吴通控股公司拟扩建生产线并建设新工厂','公司二期厂区扩产，建设MES系统升级改造。')['information_kind']=='bulletin'
    assert policy('某公司财报','公司前三季度增长，计划采购ERP系统。')['information_kind']=='bulletin'


def test_real_software_procurement_survives_generic_page_title():
    result=policy('广东某项目管理有限公司','省发展改革委价格认定业务平台项目（系统开发及升级改造）招标公告。')
    assert result['information_kind']=='opportunity'
    assert result['category']=='招采公告'
    assert policy('上海某学院AI课程改造采购公告','学院拟采购人工智能课程服务。')['information_kind']=='opportunity'


def test_social_demand_and_recruitment_do_not_enter_current_public_tender_stream():
    assert policy('公司需要软件开发','公司需要ERP系统，寻找开发供应商。')['information_kind']=='bulletin'
    assert policy('某公司招聘MES工程师','岗位职责：建设MES系统。')['information_kind']=='bulletin'


def test_public_search_does_not_keep_recruitment_and_general_demand_queries():
    from scout.search_plan import variants
    queries=variants('招聘 信息化负责人 ERP MES 建设\n企业 软件定制 寻找开发 需求\nERP 系统 升级改造 采购公告')
    assert not any('招聘' in q or '寻找开发' in q for q in queries)
    assert 'MES 招标公告' in queries
    assert '软件定制 采购意向' in queries
