from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scout.config import settings

engine = create_engine(settings().database_url, pool_pre_ping=True, hide_parameters=True)
Session = sessionmaker(engine, expire_on_commit=False)
