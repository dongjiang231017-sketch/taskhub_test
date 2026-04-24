"""Telegram Bot 私聊推送：欢迎消息、任务完成、签到成功等。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings

from users.models import FrontendUser

from .integration_config import get_telegram_bot_token
from .locale_prefs import (
    DEFAULT_PREFERRED_LANGUAGE,
    make_language_start_payload,
    normalize_preferred_language,
    supported_languages_for_bot,
)

logger = logging.getLogger(__name__)

BOT_TEXTS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "open_task_center": "🚀 打开任务中心",
        "announcement_channel": "📣 公告频道",
        "community_group": "👥 社区互助群",
        "view_task_list": "📋 查看任务列表",
        "welcome_text": "🎉 欢迎加入 TaskHub\n\n你好，{name}！\n\n💰 完成社交媒体任务赚取 USDT\n📅 每日签到领取 TH Coin\n👥 邀请好友赚返佣，持续放大收益\n\n👇 点击下方按钮，立即开始做任务。",
        "view_more_tasks": "📋 查看更多任务",
        "task_done_title": "🎉 任务完成！",
        "task_label": "✅ 任务：{task}",
        "reward_usdt": "💵 奖励：+{amount} USDT",
        "reward_th": "🪙 TH Coin：+{amount}",
        "status_done": "📌 状态：已完成",
        "task_done_tail": "继续完成更多任务赚取奖励吧！",
        "checkin_title": "📅 签到成功！",
        "makeup_title": "📅 补签成功！",
        "streak": "🔥 连续签到：{days} 天",
        "makeup_cost": "💸 补签消耗：-{amount} TH Coin",
        "got_usdt": "💵 获得奖励：+{amount} USDT",
        "got_th": "🪙 获得奖励：+{amount} TH Coin",
        "checkin_tail": "明天继续签到可获得更多奖励！",
        "makeup_tail": "继续保持签到节奏，奖励会越来越高！",
        "daily_reward_title": "🎯 每日任务奖励已到账！",
        "daily_tail": "继续完成更多每日目标吧！",
        "invite_reward_title": "🏆 邀请成就奖励已到账！",
        "achievement_label": "✅ 成就：{title}",
        "effective_invites": "👥 有效邀请：{count} 人",
        "invite_tail": "继续邀请好友，解锁更高阶奖励！",
    },
    "en": {
        "open_task_center": "🚀 Open Task Center",
        "announcement_channel": "📣 Announcement Channel",
        "community_group": "👥 Community Group",
        "view_task_list": "📋 View Task List",
        "welcome_text": "🎉 Welcome to TaskHub\n\nHi, {name}!\n\n💰 Earn USDT by completing social tasks\n📅 Check in daily to receive TH Coin\n👥 Invite friends and earn commissions continuously\n\n👇 Tap a button below to get started.",
        "view_more_tasks": "📋 More Tasks",
        "task_done_title": "🎉 Task Completed!",
        "task_label": "✅ Task: {task}",
        "reward_usdt": "💵 Reward: +{amount} USDT",
        "reward_th": "🪙 TH Coin: +{amount}",
        "status_done": "📌 Status: Completed",
        "task_done_tail": "Complete more tasks to earn more rewards!",
        "checkin_title": "📅 Check-in Successful!",
        "makeup_title": "📅 Make-up Check-in Successful!",
        "streak": "🔥 Consecutive check-ins: {days} day(s)",
        "makeup_cost": "💸 Make-up cost: -{amount} TH Coin",
        "got_usdt": "💵 Reward received: +{amount} USDT",
        "got_th": "🪙 Reward received: +{amount} TH Coin",
        "checkin_tail": "Check in again tomorrow for even more rewards!",
        "makeup_tail": "Keep your streak going and your rewards will grow!",
        "daily_reward_title": "🎯 Daily task reward received!",
        "daily_tail": "Keep completing your daily goals!",
        "invite_reward_title": "🏆 Invite achievement reward received!",
        "achievement_label": "✅ Achievement: {title}",
        "effective_invites": "👥 Effective invites: {count}",
        "invite_tail": "Invite more friends to unlock higher rewards!",
    },
    "ru": {
        "open_task_center": "🚀 Открыть центр задач",
        "announcement_channel": "📣 Канал объявлений",
        "community_group": "👥 Группа сообщества",
        "view_task_list": "📋 Список заданий",
        "welcome_text": "🎉 Добро пожаловать в TaskHub\n\nПривет, {name}!\n\n💰 Зарабатывайте USDT, выполняя социальные задания\n📅 Отмечайтесь ежедневно и получайте TH Coin\n👥 Приглашайте друзей и получайте комиссию\n\n👇 Нажмите кнопку ниже, чтобы начать.",
        "view_more_tasks": "📋 Больше заданий",
        "task_done_title": "🎉 Задание выполнено!",
        "task_label": "✅ Задание: {task}",
        "reward_usdt": "💵 Награда: +{amount} USDT",
        "reward_th": "🪙 TH Coin: +{amount}",
        "status_done": "📌 Статус: выполнено",
        "task_done_tail": "Выполняйте больше заданий и получайте больше наград!",
        "checkin_title": "📅 Отметка выполнена!",
        "makeup_title": "📅 Дополнительная отметка выполнена!",
        "streak": "🔥 Серия отметок: {days}",
        "makeup_cost": "💸 Стоимость доп. отметки: -{amount} TH Coin",
        "got_usdt": "💵 Получено: +{amount} USDT",
        "got_th": "🪙 Получено: +{amount} TH Coin",
        "checkin_tail": "Отметьтесь завтра, чтобы получить больше наград!",
        "makeup_tail": "Поддерживайте серию, и награды будут расти!",
        "daily_reward_title": "🎯 Награда за ежедневное задание получена!",
        "daily_tail": "Продолжайте выполнять ежедневные цели!",
        "invite_reward_title": "🏆 Награда за достижение по приглашениям получена!",
        "achievement_label": "✅ Достижение: {title}",
        "effective_invites": "👥 Активные приглашения: {count}",
        "invite_tail": "Приглашайте больше друзей, чтобы открыть более высокие награды!",
    },
    "ar": {
        "open_task_center": "🚀 افتح مركز المهام",
        "announcement_channel": "📣 قناة الإعلانات",
        "community_group": "👥 مجموعة المجتمع",
        "view_task_list": "📋 عرض قائمة المهام",
        "welcome_text": "🎉 مرحبًا بك في TaskHub\n\nمرحبًا، {name}!\n\n💰 اربح USDT عبر إكمال المهام الاجتماعية\n📅 سجّل حضورك يوميًا واحصل على TH Coin\n👥 ادعُ أصدقاءك واحصل على عمولات مستمرة\n\n👇 اضغط على أحد الأزرار بالأسفل للبدء.",
        "view_more_tasks": "📋 المزيد من المهام",
        "task_done_title": "🎉 تم إكمال المهمة!",
        "task_label": "✅ المهمة: {task}",
        "reward_usdt": "💵 المكافأة: +{amount} USDT",
        "reward_th": "🪙 TH Coin: +{amount}",
        "status_done": "📌 الحالة: مكتملة",
        "task_done_tail": "أكمل المزيد من المهام لتحصل على مكافآت أكثر!",
        "checkin_title": "📅 تم تسجيل الحضور!",
        "makeup_title": "📅 تم تعويض تسجيل الحضور!",
        "streak": "🔥 عدد الأيام المتتالية: {days}",
        "makeup_cost": "💸 تكلفة التعويض: -{amount} TH Coin",
        "got_usdt": "💵 تم الحصول على: +{amount} USDT",
        "got_th": "🪙 تم الحصول على: +{amount} TH Coin",
        "checkin_tail": "سجّل حضورك غدًا لتحصل على مكافآت أكبر!",
        "makeup_tail": "حافظ على الاستمرارية لتزداد مكافآتك!",
        "daily_reward_title": "🎯 تم استلام مكافأة المهمة اليومية!",
        "daily_tail": "واصل إكمال أهدافك اليومية!",
        "invite_reward_title": "🏆 تم استلام مكافأة إنجاز الدعوات!",
        "achievement_label": "✅ الإنجاز: {title}",
        "effective_invites": "👥 الدعوات الفعالة: {count}",
        "invite_tail": "ادعُ المزيد من الأصدقاء لفتح مكافآت أعلى!",
    },
    "fr": {
        "open_task_center": "🚀 Ouvrir le centre des tâches",
        "announcement_channel": "📣 Canal d'annonces",
        "community_group": "👥 Groupe communautaire",
        "view_task_list": "📋 Voir les tâches",
        "welcome_text": "🎉 Bienvenue sur TaskHub\n\nBonjour, {name} !\n\n💰 Gagnez des USDT en accomplissant des tâches sociales\n📅 Connectez-vous chaque jour pour recevoir des TH Coin\n👥 Invitez des amis et gagnez des commissions\n\n👇 Touchez un bouton ci-dessous pour commencer.",
        "view_more_tasks": "📋 Plus de tâches",
        "task_done_title": "🎉 Tâche terminée !",
        "task_label": "✅ Tâche : {task}",
        "reward_usdt": "💵 Récompense : +{amount} USDT",
        "reward_th": "🪙 TH Coin : +{amount}",
        "status_done": "📌 Statut : terminé",
        "task_done_tail": "Terminez plus de tâches pour gagner plus de récompenses !",
        "checkin_title": "📅 Pointage réussi !",
        "makeup_title": "📅 Rattrapage réussi !",
        "streak": "🔥 Série de pointage : {days}",
        "makeup_cost": "💸 Coût du rattrapage : -{amount} TH Coin",
        "got_usdt": "💵 Récompense reçue : +{amount} USDT",
        "got_th": "🪙 Récompense reçue : +{amount} TH Coin",
        "checkin_tail": "Revenez demain pour obtenir encore plus de récompenses !",
        "makeup_tail": "Gardez le rythme et vos récompenses augmenteront !",
        "daily_reward_title": "🎯 Récompense de mission quotidienne reçue !",
        "daily_tail": "Continuez à atteindre vos objectifs quotidiens !",
        "invite_reward_title": "🏆 Récompense d'invitation reçue !",
        "achievement_label": "✅ Réussite : {title}",
        "effective_invites": "👥 Invitations valides : {count}",
        "invite_tail": "Invitez plus d'amis pour débloquer des récompenses supérieures !",
    },
    "pt-BR": {
        "open_task_center": "🚀 Abrir central de tarefas",
        "announcement_channel": "📣 Canal de anúncios",
        "community_group": "👥 Grupo da comunidade",
        "view_task_list": "📋 Ver lista de tarefas",
        "welcome_text": "🎉 Bem-vindo ao TaskHub\n\nOlá, {name}!\n\n💰 Ganhe USDT concluindo tarefas sociais\n📅 Faça check-in diário para receber TH Coin\n👥 Convide amigos e ganhe comissões continuamente\n\n👇 Toque em um botão abaixo para começar.",
        "view_more_tasks": "📋 Mais tarefas",
        "task_done_title": "🎉 Tarefa concluída!",
        "task_label": "✅ Tarefa: {task}",
        "reward_usdt": "💵 Recompensa: +{amount} USDT",
        "reward_th": "🪙 TH Coin: +{amount}",
        "status_done": "📌 Status: concluída",
        "task_done_tail": "Conclua mais tarefas para ganhar mais recompensas!",
        "checkin_title": "📅 Check-in realizado!",
        "makeup_title": "📅 Check-in de reposição realizado!",
        "streak": "🔥 Sequência de check-ins: {days}",
        "makeup_cost": "💸 Custo da reposição: -{amount} TH Coin",
        "got_usdt": "💵 Recompensa recebida: +{amount} USDT",
        "got_th": "🪙 Recompensa recebida: +{amount} TH Coin",
        "checkin_tail": "Volte amanhã para receber ainda mais recompensas!",
        "makeup_tail": "Mantenha sua sequência para aumentar suas recompensas!",
        "daily_reward_title": "🎯 Recompensa da tarefa diária recebida!",
        "daily_tail": "Continue concluindo suas metas diárias!",
        "invite_reward_title": "🏆 Recompensa de conquista por convite recebida!",
        "achievement_label": "✅ Conquista: {title}",
        "effective_invites": "👥 Convites válidos: {count}",
        "invite_tail": "Convide mais amigos para desbloquear recompensas maiores!",
    },
    "es": {
        "open_task_center": "🚀 Abrir centro de tareas",
        "announcement_channel": "📣 Canal de anuncios",
        "community_group": "👥 Grupo de comunidad",
        "view_task_list": "📋 Ver lista de tareas",
        "welcome_text": "🎉 Bienvenido a TaskHub\n\nHola, {name}!\n\n💰 Gana USDT completando tareas sociales\n📅 Haz check-in diario para recibir TH Coin\n👥 Invita amigos y gana comisiones de forma continua\n\n👇 Toca uno de los botones para comenzar.",
        "view_more_tasks": "📋 Más tareas",
        "task_done_title": "🎉 ¡Tarea completada!",
        "task_label": "✅ Tarea: {task}",
        "reward_usdt": "💵 Recompensa: +{amount} USDT",
        "reward_th": "🪙 TH Coin: +{amount}",
        "status_done": "📌 Estado: completada",
        "task_done_tail": "¡Completa más tareas para ganar más recompensas!",
        "checkin_title": "📅 ¡Check-in exitoso!",
        "makeup_title": "📅 ¡Check-in de recuperación exitoso!",
        "streak": "🔥 Racha de check-in: {days}",
        "makeup_cost": "💸 Costo de recuperación: -{amount} TH Coin",
        "got_usdt": "💵 Recompensa obtenida: +{amount} USDT",
        "got_th": "🪙 Recompensa obtenida: +{amount} TH Coin",
        "checkin_tail": "¡Vuelve mañana para obtener aún más recompensas!",
        "makeup_tail": "¡Mantén tu racha para conseguir mayores recompensas!",
        "daily_reward_title": "🎯 ¡Recompensa de tarea diaria recibida!",
        "daily_tail": "¡Sigue completando tus objetivos diarios!",
        "invite_reward_title": "🏆 ¡Recompensa por logro de invitación recibida!",
        "achievement_label": "✅ Logro: {title}",
        "effective_invites": "👥 Invitaciones válidas: {count}",
        "invite_tail": "¡Invita a más amigos para desbloquear mejores recompensas!",
    },
    "vi": {
        "open_task_center": "🚀 Mở trung tâm nhiệm vụ",
        "announcement_channel": "📣 Kênh thông báo",
        "community_group": "👥 Nhóm cộng đồng",
        "view_task_list": "📋 Xem danh sách nhiệm vụ",
        "welcome_text": "🎉 Chào mừng đến với TaskHub\n\nXin chào, {name}!\n\n💰 Kiếm USDT bằng cách hoàn thành các nhiệm vụ xã hội\n📅 Điểm danh hằng ngày để nhận TH Coin\n👥 Mời bạn bè và nhận hoa hồng liên tục\n\n👇 Nhấn nút bên dưới để bắt đầu.",
        "view_more_tasks": "📋 Xem thêm nhiệm vụ",
        "task_done_title": "🎉 Hoàn thành nhiệm vụ!",
        "task_label": "✅ Nhiệm vụ: {task}",
        "reward_usdt": "💵 Phần thưởng: +{amount} USDT",
        "reward_th": "🪙 TH Coin: +{amount}",
        "status_done": "📌 Trạng thái: đã hoàn thành",
        "task_done_tail": "Hãy hoàn thành thêm nhiệm vụ để nhận nhiều phần thưởng hơn!",
        "checkin_title": "📅 Điểm danh thành công!",
        "makeup_title": "📅 Bù điểm danh thành công!",
        "streak": "🔥 Chuỗi điểm danh liên tiếp: {days}",
        "makeup_cost": "💸 Chi phí bù điểm danh: -{amount} TH Coin",
        "got_usdt": "💵 Đã nhận: +{amount} USDT",
        "got_th": "🪙 Đã nhận: +{amount} TH Coin",
        "checkin_tail": "Hãy quay lại ngày mai để nhận thêm phần thưởng!",
        "makeup_tail": "Giữ nhịp điểm danh để phần thưởng tăng dần!",
        "daily_reward_title": "🎯 Đã nhận phần thưởng nhiệm vụ hằng ngày!",
        "daily_tail": "Tiếp tục hoàn thành mục tiêu hằng ngày!",
        "invite_reward_title": "🏆 Đã nhận phần thưởng thành tích mời bạn!",
        "achievement_label": "✅ Thành tích: {title}",
        "effective_invites": "👥 Lời mời hợp lệ: {count}",
        "invite_tail": "Mời thêm bạn bè để mở khóa phần thưởng cao hơn!",
    },
}

TASK_TITLE_TEXTS: dict[str, dict[str, str]] = {
    "telegram_join": {
        "zh-CN": "加入 Telegram 群组",
        "en": "Join Telegram Group",
        "ru": "Вступить в Telegram-группу",
        "ar": "انضم إلى مجموعة Telegram",
        "fr": "Rejoindre le groupe Telegram",
        "pt-BR": "Entrar no grupo do Telegram",
        "es": "Unirse al grupo de Telegram",
        "vi": "Tham gia nhóm Telegram",
    },
    "link_twitter": {
        "zh-CN": "绑定 Twitter 账号",
        "en": "Link Twitter Account",
        "ru": "Привязать аккаунт Twitter",
        "ar": "اربط حساب Twitter",
        "fr": "Lier le compte Twitter",
        "pt-BR": "Vincular conta do Twitter",
        "es": "Vincular cuenta de Twitter",
        "vi": "Liên kết tài khoản Twitter",
    },
    "bind_tiktok": {
        "zh-CN": "绑定 TikTok 账号",
        "en": "Bind TikTok Account",
        "ru": "Привязать аккаунт TikTok",
        "ar": "اربط حساب TikTok",
        "fr": "Lier le compte TikTok",
        "pt-BR": "Vincular conta do TikTok",
        "es": "Vincular cuenta de TikTok",
        "vi": "Liên kết tài khoản TikTok",
    },
    "bind_youtube": {
        "zh-CN": "绑定 YouTube 频道",
        "en": "Bind YouTube Channel",
        "ru": "Привязать канал YouTube",
        "ar": "اربط قناة YouTube",
        "fr": "Lier la chaîne YouTube",
        "pt-BR": "Vincular canal do YouTube",
        "es": "Vincular canal de YouTube",
        "vi": "Liên kết kênh YouTube",
    },
    "bind_instagram": {
        "zh-CN": "绑定 Instagram 账号",
        "en": "Bind Instagram Account",
        "ru": "Привязать аккаунт Instagram",
        "ar": "اربط حساب Instagram",
        "fr": "Lier le compte Instagram",
        "pt-BR": "Vincular conta do Instagram",
        "es": "Vincular cuenta de Instagram",
        "vi": "Liên kết tài khoản Instagram",
    },
    "bind_facebook": {
        "zh-CN": "绑定 Facebook 账号",
        "en": "Bind Facebook Account",
        "ru": "Привязать аккаунт Facebook",
        "ar": "اربط حساب Facebook",
        "fr": "Lier le compte Facebook",
        "pt-BR": "Vincular conta do Facebook",
        "es": "Vincular cuenta de Facebook",
        "vi": "Liên kết tài khoản Facebook",
    },
    "follow_twitter": {
        "zh-CN": "关注 Twitter",
        "en": "Follow Twitter",
        "ru": "Подписаться на Twitter",
        "ar": "تابع Twitter",
        "fr": "Suivre Twitter",
        "pt-BR": "Seguir no Twitter",
        "es": "Seguir en Twitter",
        "vi": "Theo dõi Twitter",
    },
    "follow_instagram": {
        "zh-CN": "关注 Instagram",
        "en": "Follow Instagram",
        "ru": "Подписаться на Instagram",
        "ar": "تابع Instagram",
        "fr": "Suivre Instagram",
        "pt-BR": "Seguir no Instagram",
        "es": "Seguir en Instagram",
        "vi": "Theo dõi Instagram",
    },
    "follow_tiktok": {
        "zh-CN": "关注 TikTok",
        "en": "Follow TikTok",
        "ru": "Подписаться на TikTok",
        "ar": "تابع TikTok",
        "fr": "Suivre TikTok",
        "pt-BR": "Seguir no TikTok",
        "es": "Seguir en TikTok",
        "vi": "Theo dõi TikTok",
    },
    "like_twitter": {
        "zh-CN": "点赞 Twitter",
        "en": "Like Twitter Post",
        "ru": "Лайкнуть пост в Twitter",
        "ar": "أعجب بمنشور Twitter",
        "fr": "Aimer une publication Twitter",
        "pt-BR": "Curtir publicação no Twitter",
        "es": "Dar me gusta a publicación de Twitter",
        "vi": "Thích bài đăng Twitter",
    },
    "like_instagram": {
        "zh-CN": "点赞 Instagram",
        "en": "Like Instagram Post",
        "ru": "Лайкнуть пост в Instagram",
        "ar": "أعجب بمنشور Instagram",
        "fr": "Aimer une publication Instagram",
        "pt-BR": "Curtir publicação no Instagram",
        "es": "Dar me gusta a publicación de Instagram",
        "vi": "Thích bài đăng Instagram",
    },
    "like_tiktok": {
        "zh-CN": "点赞 TikTok",
        "en": "Like TikTok Post",
        "ru": "Лайкнуть видео в TikTok",
        "ar": "أعجب بفيديو TikTok",
        "fr": "Aimer une publication TikTok",
        "pt-BR": "Curtir publicação no TikTok",
        "es": "Dar me gusta a publicación de TikTok",
        "vi": "Thích bài đăng TikTok",
    },
    "daily_3": {
        "zh-CN": "完成 3 个任务",
        "en": "Complete 3 Tasks",
        "ru": "Выполнить 3 задания",
        "ar": "أكمل 3 مهام",
        "fr": "Terminer 3 tâches",
        "pt-BR": "Concluir 3 tarefas",
        "es": "Completar 3 tareas",
        "vi": "Hoàn thành 3 nhiệm vụ",
    },
    "daily_10": {
        "zh-CN": "完成 10 个任务",
        "en": "Complete 10 Tasks",
        "ru": "Выполнить 10 заданий",
        "ar": "أكمل 10 مهام",
        "fr": "Terminer 10 tâches",
        "pt-BR": "Concluir 10 tarefas",
        "es": "Completar 10 tareas",
        "vi": "Hoàn thành 10 nhiệm vụ",
    },
    "referral_expert": {
        "zh-CN": "推荐专家",
        "en": "Referral Expert",
        "ru": "Эксперт по приглашениям",
        "ar": "خبير الإحالات",
        "fr": "Expert en parrainage",
        "pt-BR": "Especialista em indicações",
        "es": "Experto en referidos",
        "vi": "Chuyên gia giới thiệu",
    },
}

TASK_TITLE_ALIASES: dict[str, str] = {
    "加入 telegram 群组": "telegram_join",
    "加入 telegram 群": "telegram_join",
    "join telegram group": "telegram_join",
    "link twitter account": "link_twitter",
    "绑定 twitter 账号": "link_twitter",
    "绑定推特账号": "link_twitter",
    "绑定 x 账号": "link_twitter",
    "绑定 tiktok 账号": "bind_tiktok",
    "绑定 youtube 频道": "bind_youtube",
    "绑定 youtube 账号": "bind_youtube",
    "绑定 instagram 账号": "bind_instagram",
    "绑定 ins 账号": "bind_instagram",
    "绑定 facebook 账号": "bind_facebook",
    "follow twitter": "follow_twitter",
    "关注 twitter": "follow_twitter",
    "关注 x": "follow_twitter",
    "关注推特": "follow_twitter",
    "follow instagram": "follow_instagram",
    "关注 instagram": "follow_instagram",
    "关注 ins": "follow_instagram",
    "follow tiktok": "follow_tiktok",
    "关注 tiktok": "follow_tiktok",
    "like twitter post": "like_twitter",
    "点赞 twitter": "like_twitter",
    "点赞 x": "like_twitter",
    "点赞推特": "like_twitter",
    "like instagram post": "like_instagram",
    "点赞 instagram": "like_instagram",
    "点赞 ins": "like_instagram",
    "like tiktok post": "like_tiktok",
    "点赞 tiktok": "like_tiktok",
    "完成 3 个任务": "daily_3",
    "完成 10 个任务": "daily_10",
    "推荐专家": "referral_expert",
}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _language_code(raw: str | None) -> str:
    return normalize_preferred_language(raw) or DEFAULT_PREFERRED_LANGUAGE


def _bot_text(language: str | None, key: str, **params: Any) -> str:
    code = _language_code(language)
    template = BOT_TEXTS.get(code, {}).get(key) or BOT_TEXTS[DEFAULT_PREFERRED_LANGUAGE].get(key) or key
    if not params:
        return template
    return template.format(**params)


def _bot_dynamic_title(title: Any, language: str | None) -> str:
    text = _clean_text(title)
    if not text:
        return ""
    normalized = " ".join(text.replace("Tleagram", "Telegram").split()).lower()
    alias = TASK_TITLE_ALIASES.get(normalized)
    if not alias:
        return text.replace("Tleagram", "Telegram")
    code = _language_code(language)
    rows = TASK_TITLE_TEXTS.get(alias) or {}
    return rows.get(code) or rows.get(DEFAULT_PREFERRED_LANGUAGE) or text


def _preferred_language_for_user(user: FrontendUser | None, fallback: str | None = None) -> str:
    if user is not None:
        return _language_code(getattr(user, "preferred_language", None) or fallback)
    return _language_code(fallback)


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _fmt_amount(value: Any) -> str:
    dec = _to_decimal(value)
    text = format(dec, "f")
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _telegram_api_post(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    token = get_telegram_bot_token()
    if not token:
        return None
    api = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        api,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8") if resp else ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.warning("telegram push %s failed: %s %s", method, exc.code, body)
        return None
    except urllib.error.URLError as exc:
        logger.warning("telegram push %s failed: %s", method, exc)
        return None

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("telegram push %s returned invalid json: %r", method, raw[:500])
        return None

    if not parsed.get("ok", False):
        logger.warning("telegram push %s not ok: %s", method, parsed)
        return None
    return parsed


def _bot_mini_app_url() -> str:
    direct = _clean_text(getattr(settings, "TELEGRAM_MINI_APP_URL", ""))
    if direct:
        return direct
    bot = _clean_text(getattr(settings, "TELEGRAM_BOT_USERNAME", "")).lstrip("@")
    short = _clean_text(getattr(settings, "TELEGRAM_MINI_APP_SHORT_NAME", ""))
    if bot and short:
        return f"https://t.me/{bot}/{short}"
    return ""


def _with_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != key]
    pairs.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(pairs)))


def _mini_app_url_for_language(code: str) -> str:
    normalized = _language_code(code)
    direct = _clean_text(getattr(settings, "TELEGRAM_MINI_APP_URL", ""))
    bot = _clean_text(getattr(settings, "TELEGRAM_BOT_USERNAME", "")).lstrip("@")
    short = _clean_text(getattr(settings, "TELEGRAM_MINI_APP_SHORT_NAME", ""))
    if bot and short:
        base = f"https://t.me/{bot}/{short}"
        return _with_query_param(base, "startapp", make_language_start_payload(normalized))
    if direct:
        return _with_query_param(direct, "lang", normalized)
    return _bot_mini_app_url()


def _announcement_url() -> str:
    return _clean_text(getattr(settings, "TELEGRAM_ANNOUNCEMENT_URL", ""))


def _community_url() -> str:
    return _clean_text(getattr(settings, "TELEGRAM_COMMUNITY_URL", ""))


def _welcome_image_url() -> str:
    return _clean_text(getattr(settings, "TELEGRAM_BOT_WELCOME_IMAGE_URL", ""))


def _welcome_text(display_name: str, *, language: str | None = None) -> str:
    custom = _clean_text(getattr(settings, "TELEGRAM_BOT_WELCOME_TEXT", ""))
    if custom:
        return custom.replace("{name}", display_name)
    return _bot_text(language, "welcome_text", name=display_name)


def _inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict[str, Any] | None:
    inline_rows: list[list[dict[str, str]]] = []
    for row in rows:
        btns = []
        for text, url in row:
            if not _clean_text(text) or not _clean_text(url):
                continue
            btns.append({"text": text, "url": url})
        if btns:
            inline_rows.append(btns)
    if not inline_rows:
        return None
    return {"inline_keyboard": inline_rows}


def _welcome_keyboard(language: str | None = None) -> dict[str, Any] | None:
    app_url = _bot_mini_app_url()
    announce_url = _announcement_url()
    community_url = _community_url()
    rows: list[list[tuple[str, str]]] = []
    first_row: list[tuple[str, str]] = []
    if app_url:
        first_row.append((_bot_text(language, "open_task_center"), app_url))
    if announce_url:
        first_row.append((_bot_text(language, "announcement_channel"), announce_url))
    if first_row:
        rows.append(first_row[:2])
    second_row: list[tuple[str, str]] = []
    if community_url:
        second_row.append((_bot_text(language, "community_group"), community_url))
    if app_url:
        second_row.append((_bot_text(language, "view_task_list"), app_url))
    if second_row:
        rows.append(second_row[:2])
    language_row_set: list[list[tuple[str, str]]] = []
    for row in supported_languages_for_bot():
        buttons: list[tuple[str, str]] = []
        for label, code in row:
            lang_url = _mini_app_url_for_language(code)
            if lang_url:
                buttons.append((label, lang_url))
        if buttons:
            language_row_set.append(buttons)
    rows.extend(language_row_set)
    return _inline_keyboard(rows)


def _task_cta_keyboard(language: str | None = None) -> dict[str, Any] | None:
    app_url = _bot_mini_app_url()
    community_url = _community_url()
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    if app_url:
        row.append((_bot_text(language, "view_more_tasks"), app_url))
    if community_url:
        row.append((_bot_text(language, "community_group"), community_url))
    if row:
        rows.append(row[:2])
    return _inline_keyboard(rows)


def send_bot_message(chat_id: int | str, text: str, *, reply_markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _telegram_api_post("sendMessage", payload)


def send_bot_photo(
    chat_id: int | str,
    photo_url: str,
    *,
    caption: str = "",
    reply_markup: dict[str, Any] | None = None,
) -> None:
    if not _clean_text(photo_url):
        return
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption:
        payload["caption"] = caption
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _telegram_api_post("sendPhoto", payload)


def send_welcome_message(
    chat_id: int | str,
    *,
    first_name: str | None = None,
    preferred_language: str | None = None,
) -> None:
    name = _clean_text(first_name) or "朋友"
    language = _language_code(preferred_language)
    keyboard = _welcome_keyboard(language)
    image_url = _welcome_image_url()
    if image_url:
        send_bot_photo(chat_id, image_url)
    send_bot_message(chat_id, _welcome_text(name, language=language), reply_markup=keyboard)


def _user_chat_id(user: FrontendUser) -> int | None:
    tg = getattr(user, "telegram_id", None)
    if tg is None:
        return None
    try:
        return int(tg)
    except (TypeError, ValueError):
        return None


def send_task_completion_message(application, granted: dict[str, Any] | None) -> None:
    user = getattr(application, "applicant", None)
    if user is None:
        return
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return
    language = _preferred_language_for_user(user)

    reason = _clean_text((granted or {}).get("reason"))
    if reason in {"db_error", "already_paid"}:
        return

    lines = [
        _bot_text(language, "task_done_title"),
        "",
        _bot_text(language, "task_label", task=_bot_dynamic_title(application.task.title, language)),
    ]
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(_bot_text(language, "reward_usdt", amount=_fmt_amount(usdt)))
    if th_coin > 0:
        lines.append(_bot_text(language, "reward_th", amount=_fmt_amount(th_coin)))
    if usdt <= 0 and th_coin <= 0:
        lines.append(_bot_text(language, "status_done"))
    lines.extend(["", _bot_text(language, "task_done_tail")])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard(language))


def send_checkin_success_message(
    user: FrontendUser,
    *,
    streak_days: int,
    granted: dict[str, Any] | None,
    is_makeup: bool = False,
    spent_th_coin: Any = None,
) -> None:
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return
    language = _preferred_language_for_user(user)

    title = _bot_text(language, "makeup_title" if is_makeup else "checkin_title")
    lines = [title, "", _bot_text(language, "streak", days=max(0, int(streak_days or 0)))]
    spent = _to_decimal(spent_th_coin)
    if is_makeup and spent > 0:
        lines.append(_bot_text(language, "makeup_cost", amount=_fmt_amount(spent)))
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(_bot_text(language, "got_usdt", amount=_fmt_amount(usdt)))
    if th_coin > 0:
        lines.append(_bot_text(language, "got_th", amount=_fmt_amount(th_coin)))
    tail = _bot_text(language, "makeup_tail" if is_makeup else "checkin_tail")
    lines.extend(["", tail])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard(language))


def send_daily_task_claim_message(user: FrontendUser, definition, granted: dict[str, Any] | None) -> None:
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return
    language = _preferred_language_for_user(user)

    lines = [
        _bot_text(language, "daily_reward_title"),
        "",
        _bot_text(language, "task_label", task=_bot_dynamic_title(definition.title, language)),
    ]
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(_bot_text(language, "reward_usdt", amount=_fmt_amount(usdt)))
    if th_coin > 0:
        lines.append(_bot_text(language, "reward_th", amount=_fmt_amount(th_coin)))
    lines.extend(["", _bot_text(language, "daily_tail")])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard(language))


def send_invite_achievement_claim_message(
    user: FrontendUser,
    tier,
    granted: dict[str, Any] | None,
    *,
    invited_total: int,
) -> None:
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return
    language = _preferred_language_for_user(user)

    lines = [
        _bot_text(language, "invite_reward_title"),
        "",
        _bot_text(language, "achievement_label", title=_bot_dynamic_title(tier.title, language)),
        _bot_text(language, "effective_invites", count=max(0, int(invited_total or 0))),
    ]
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(_bot_text(language, "reward_usdt", amount=_fmt_amount(usdt)))
    if th_coin > 0:
        lines.append(_bot_text(language, "reward_th", amount=_fmt_amount(th_coin)))
    lines.extend(["", _bot_text(language, "invite_tail")])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard(language))
