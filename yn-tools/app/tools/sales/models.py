"""Sales automation models - migrated from standalone sales-automation app.

Changes from original:
- org_id replaced with user_id (portal uses individual user accounts)
- Removed User/Organization/OrgMember models (handled by portal)
- AppSetting replaced with SalesSmtpConfig (dedicated table)
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SalesCompany(Base):
    __tablename__ = "sales_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    website_url: Mapped[str | None] = mapped_column(String(500))
    google_maps_url: Mapped[str | None] = mapped_column(String(500))
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    industry: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    contacts: Mapped[list["SalesContact"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    crm_status: Mapped["SalesCrmStatus | None"] = relationship(
        back_populates="company", uselist=False, cascade="all, delete-orphan"
    )


class SalesContact(Base):
    __tablename__ = "sales_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("sales_companies.id"))
    email: Mapped[str | None] = mapped_column(String(255))
    email_type: Mapped[str | None] = mapped_column(String(50))
    contact_form_url: Mapped[str | None] = mapped_column(String(500))
    sns_instagram: Mapped[str | None] = mapped_column(String(255))
    sns_twitter: Mapped[str | None] = mapped_column(String(255))
    sns_facebook: Mapped[str | None] = mapped_column(String(255))
    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped["SalesCompany"] = relationship(back_populates="contacts")


class SalesCrmStatus(Base):
    __tablename__ = "sales_crm_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("sales_companies.id"), unique=True
    )
    status: Mapped[str] = mapped_column(String(50), default="未営業")
    score: Mapped[int] = mapped_column(Integer, default=0)
    memo: Mapped[str | None] = mapped_column(Text)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    company: Mapped["SalesCompany"] = relationship(back_populates="crm_status")


class SalesCampaign(Base):
    __tablename__ = "sales_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    subject_template: Mapped[str | None] = mapped_column(String(500))
    body_template: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SalesOutreachLog(Base):
    __tablename__ = "sales_outreach_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("sales_companies.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("sales_contacts.id"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("sales_campaigns.id"))
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SalesSmtpConfig(Base):
    __tablename__ = "sales_smtp_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    smtp_host: Mapped[str] = mapped_column(String(255), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=465)
    smtp_user: Mapped[str] = mapped_column(String(255), default="")
    smtp_password: Mapped[str] = mapped_column(String(500), default="")
    smtp_from_name: Mapped[str] = mapped_column(String(255), default="")
