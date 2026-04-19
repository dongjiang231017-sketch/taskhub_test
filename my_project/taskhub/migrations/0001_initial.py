# Generated manually for taskhub.

import decimal
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("users", "0002_frontenduser_membership_level_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(db_comment="任务分类名称", max_length=50, unique=True, verbose_name="分类名称")),
                ("slug", models.SlugField(db_comment="任务分类唯一标识", max_length=60, unique=True, verbose_name="分类标识")),
                (
                    "description",
                    models.CharField(
                        blank=True,
                        db_comment="分类简介",
                        max_length=255,
                        null=True,
                        verbose_name="分类描述",
                    ),
                ),
                ("sort_order", models.IntegerField(db_comment="数值越大越靠前", default=0, verbose_name="排序权重")),
                ("is_active", models.BooleanField(db_comment="前台是否展示", default=True, verbose_name="是否启用")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_comment="分类创建时间", verbose_name="创建时间")),
            ],
            options={
                "verbose_name": "任务分类",
                "verbose_name_plural": "任务分类",
                "db_table": "task_category",
                "ordering": ("-sort_order", "name"),
            },
        ),
        migrations.CreateModel(
            name="ApiToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(db_comment="鉴权令牌", max_length=64, unique=True, verbose_name="Token")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_comment="Token 创建时间", verbose_name="签发时间")),
                (
                    "last_used_at",
                    models.DateTimeField(
                        blank=True,
                        db_comment="最近一次鉴权请求时间",
                        null=True,
                        verbose_name="最近使用时间",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        db_comment="Token 对应的用户",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="api_token",
                        to="users.frontenduser",
                        verbose_name="所属用户",
                    ),
                ),
            ],
            options={
                "verbose_name": "API Token",
                "verbose_name_plural": "API Token",
                "db_table": "task_api_token",
            },
        ),
        migrations.CreateModel(
            name="Task",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(db_comment="任务标题", max_length=200, verbose_name="任务标题")),
                ("description", models.TextField(db_comment="任务详情", verbose_name="任务描述")),
                (
                    "budget",
                    models.DecimalField(
                        db_comment="任务预算金额",
                        decimal_places=2,
                        default=decimal.Decimal("0.00"),
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))],
                        verbose_name="预算金额",
                    ),
                ),
                ("reward_unit", models.CharField(db_comment="预算币种", default="CNY", max_length=12, verbose_name="币种")),
                (
                    "deadline",
                    models.DateTimeField(
                        blank=True,
                        db_comment="任务报名或完成截止时间",
                        null=True,
                        verbose_name="截止时间",
                    ),
                ),
                ("region", models.CharField(blank=True, db_comment="任务执行地区", max_length=120, null=True, verbose_name="任务地区")),
                ("applicants_limit", models.PositiveIntegerField(db_comment="任务可录用人数", default=1, verbose_name="需求人数")),
                ("contact_name", models.CharField(blank=True, db_comment="联系姓名", max_length=50, null=True, verbose_name="联系人")),
                ("contact_phone", models.CharField(blank=True, db_comment="联系方式", max_length=30, null=True, verbose_name="联系电话")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "草稿"),
                            ("open", "可报名"),
                            ("in_progress", "进行中"),
                            ("completed", "已完成"),
                            ("closed", "已关闭"),
                        ],
                        db_comment="任务当前状态",
                        default="open",
                        max_length=20,
                        verbose_name="任务状态",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_comment="任务创建时间", verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, db_comment="任务更新时间", verbose_name="更新时间")),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        db_comment="任务所属分类",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tasks",
                        to="taskhub.taskcategory",
                        verbose_name="任务分类",
                    ),
                ),
                (
                    "publisher",
                    models.ForeignKey(
                        db_comment="任务发布用户ID",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="published_tasks",
                        to="users.frontenduser",
                        verbose_name="发布人",
                    ),
                ),
            ],
            options={
                "verbose_name": "任务",
                "verbose_name_plural": "任务",
                "db_table": "task_job",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="TaskApplication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("proposal", models.TextField(blank=True, db_comment="报名留言或补充说明", null=True, verbose_name="报名说明")),
                (
                    "quoted_price",
                    models.DecimalField(
                        blank=True,
                        db_comment="报名时的报价",
                        decimal_places=2,
                        max_digits=12,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))],
                        verbose_name="报价",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "待处理"),
                            ("accepted", "已录用"),
                            ("rejected", "已拒绝"),
                            ("cancelled", "已取消"),
                        ],
                        db_comment="报名处理状态",
                        default="pending",
                        max_length=20,
                        verbose_name="报名状态",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_comment="报名创建时间", verbose_name="报名时间")),
                (
                    "decided_at",
                    models.DateTimeField(
                        blank=True,
                        db_comment="发布人处理报名的时间",
                        null=True,
                        verbose_name="处理时间",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, db_comment="更新时间", verbose_name="更新时间")),
                (
                    "applicant",
                    models.ForeignKey(
                        db_comment="报名用户ID",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="task_applications",
                        to="users.frontenduser",
                        verbose_name="报名用户",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        db_comment="被报名的任务ID",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="applications",
                        to="taskhub.task",
                        verbose_name="报名任务",
                    ),
                ),
            ],
            options={
                "verbose_name": "任务报名",
                "verbose_name_plural": "任务报名",
                "db_table": "task_application",
                "ordering": ("-created_at",),
                "unique_together": {("task", "applicant")},
            },
        ),
    ]
