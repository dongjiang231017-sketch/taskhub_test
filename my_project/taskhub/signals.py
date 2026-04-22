"""Task 生命周期信号：任务不可再接时自动释放未完成报名。"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Task
from .task_lifecycle import release_incomplete_applications_for_task_ids, task_terminal_should_release_takers


@receiver(post_save, sender=Task)
def task_post_save_release_incomplete_applications(sender, instance: Task, created: bool, **kwargs):
    if created:
        return
    if not task_terminal_should_release_takers(instance):
        return
    release_incomplete_applications_for_task_ids([instance.pk])
