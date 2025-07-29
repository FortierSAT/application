# core/db/models.py

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Integer, String, Text

from sqlalchemy.orm import declarative_base

Base = declarative_base()

class WorklistStaging(Base):
    __tablename__ = "worklist_staging"

    ccfid = Column(Text, primary_key=True)
    first_name = Column(Text)
    last_name = Column(Text)
    primary_id = Column(Text)
    company_code = Column(Text)
    company_name = Column(Text)
    collection_site = Column(Text)
    collection_site_id = Column(Text)
    laboratory = Column(Text)
    location = Column(Text)
    test_reason = Column(Text)
    test_result = Column(Text)
    positive_for = Column(Text)
    test_type = Column(Text)
    regulation = Column(Text)
    regulation_body = Column(Text)
    bat_value = Column(Text)
    collection_date = Column(Date)
    mro_received = Column(Date)
    reviewed = Column(Boolean, default=False)
    uploaded_timestamp = Column(DateTime)

class UploadedCCFID(Base):
    __tablename__ = "uploaded_ccfid"

    ccfid = Column(Text, primary_key=True)
    uploaded_timestamp = Column(Text)


class CollectionSite(Base):
    __tablename__ = "collection_sites"

    Record_id = Column(Text, primary_key=True)
    Collection_Site = Column(Text)
    Collection_Site_ID = Column(Text)


class Company(Base):
    __tablename__ = "account_info"

    account_id = Column(Text, primary_key=True)
    account_code = Column(Text, unique=True, index=True)
    account_name = Column(Text)
    account_i3_code = Column(Integer, nullable=True, index=True)


class Laboratory(Base):
    __tablename__ = "laboratories"

    Record_id = Column(Text, primary_key=True)
    Laboratory = Column(Text, unique=True, index=True)
