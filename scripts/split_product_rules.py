"""Run in backend container after r018; split only the three named legacy categories.

All replacements are stopped pending confirmation. Old rules are retained for task
history but retired from the normal configuration list. Re-running is a no-op.
"""
from sqlalchemy import select
from scout.db import Session
from scout.models import Rule
from scout.product_rules import ProductSpec

ALIASES = {
    'ERP 系统': ('ERP', ['企业资源计划系统']),
    'ERP 升级改造': ('ERP 升级改造', []),
    'MES 制造执行系统': ('MES', ['制造执行系统']),
    'WMS 仓储管理系统': ('WMS', ['仓储管理系统']),
    'HR 人力资源系统': ('HR', ['人力资源系统']),
    'OA 协同办公系统': ('OA', ['协同办公系统']),
    'CRM 客户管理系统': ('CRM', ['客户关系管理系统']),
    'AI 智能体': ('AI 智能体', ['AI Agent', '人工智能体']),
    'AI Agent': ('AI 智能体', ['AI Agent', '人工智能体']),
    'RAG 检索增强生成': ('RAG', ['检索增强生成']),
    '系统集成 数据对接': ('系统集成', []),
}
CATEGORIES = ('财务与ERP', '财务与 ERP', '企业管理与智能制造', 'AI 智能体与知识库')


def run():
    with Session.begin() as db:
        legacy = db.scalars(select(Rule).where(Rule.name.in_(CATEGORIES), Rule.source_type=='public_tender', Rule.provider=='searxng').with_for_update()).all()
        all_rules = db.scalars(select(Rule).where(Rule.source_type=='public_tender')).all()
        names={r.name.casefold() for r in all_rules if (r.search_spec or {}).get('product')}
        count=0
        for old in legacy:
            if old.search_spec:
                continue
            for seed in old.query.splitlines():
                seed=seed.strip()
                if not seed:
                    continue
                product, aliases=ALIASES.get(seed, (seed, []))
                specs=[ProductSpec(product=product,synonyms=aliases)]
                if seed=='系统集成 数据对接':
                    specs.append(ProductSpec(product='数据对接'))
                for spec in specs:
                    if spec.product.casefold() in names:
                        continue
                    db.add(Rule(name=spec.product, search_spec=spec.model_dump(), query='\n'.join(spec.searches()),provider='searxng',source_type='public_tender',enabled=False,interval_seconds=0,max_results=20))
                    names.add(spec.product.casefold())
                    count+=1
            old.enabled=False
            old.version+=1
            old.search_spec={'retired':True, 'reason':'split_into_product_rules'}
        print(f'Created {count} stopped product rules; history retained.')


if __name__=='__main__':
    run()
