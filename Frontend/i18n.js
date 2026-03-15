/**
 * Bridge IDE — Internationalization (i18n)
 * 5 Languages: EN (default), DE, RU, ZH, ES
 * Usage: t('key') returns string in current language
 * Language stored in localStorage('bridge_language'), default: 'en'
 */

const BRIDGE_I18N = {

// ─── SIDEBAR ───
sidebarNewProject:        { en:"New Project",        de:"Neues Projekt",          ru:"Новый проект",          zh:"新建项目",           es:"Nuevo proyecto" },
sidebarOrgChart:          { en:"Org Chart",           de:"Organigramm",            ru:"Оргструктура",          zh:"组织架构",           es:"Organigrama" },
sidebarTasks:             { en:"Tasks",               de:"Aufgaben",               ru:"Задачи",                zh:"任务",               es:"Tareas" },
sidebarControlCenter:     { en:"Control Center",      de:"Control Center",         ru:"Центр управления",      zh:"控制中心",           es:"Centro de control" },
sidebarSearchProjects:    { en:"Search projects...",  de:"Projekte durchsuchen...",ru:"Поиск проектов...",      zh:"搜索项目...",         es:"Buscar proyectos..." },
sidebarFavorites:         { en:"Favorites",           de:"Favoriten",              ru:"Избранное",             zh:"收藏",               es:"Favoritos" },
sidebarProjects:          { en:"Projects",            de:"Projekte",               ru:"Проекты",               zh:"项目",               es:"Proyectos" },
sidebarActivity:          { en:"Activity",            de:"Aktivitaet",             ru:"Активность",            zh:"活动",               es:"Actividad" },
sidebarNoActivity:        { en:"No activity",         de:"Keine Aktivitaet",       ru:"Нет активности",        zh:"暂无活动",           es:"Sin actividad" },
sidebarProjectsLoadFailed:{ en:"Could not load projects",de:"Projekte konnten nicht geladen werden",ru:"Не удалось загрузить проекты",zh:"无法加载项目",es:"No se pudieron cargar los proyectos" },
sidebarToggleLabel:       { en:"Toggle sidebar",      de:"Seitenleiste ein/ausblenden",ru:"Показать/скрыть панель",zh:"切换侧栏",      es:"Mostrar/ocultar barra lateral" },
sidebarOnline:            { en:"online",              de:"online",                 ru:"онлайн",                zh:"在线",               es:"en línea" },
sidebarMore:              { en:"More",                de:"Weitere",                ru:"Ещё",                   zh:"更多",               es:"Más" },
sidebarResizeHandle:      { en:"Resize",              de:"Groesse anpassen",       ru:"Изменить размер",       zh:"调整大小",           es:"Redimensionar" },

// ─── SETTINGS MODAL ───
settingsTitle:            { en:"Settings",            de:"Einstellungen",          ru:"Настройки",             zh:"设置",               es:"Configuración" },
settingsClose:            { en:"Close",               de:"Schliessen",             ru:"Закрыть",               zh:"关闭",               es:"Cerrar" },
settingsTabSubscriptions: { en:"Subscriptions",       de:"Subscriptions",          ru:"Подписки",              zh:"订阅",               es:"Suscripciones" },
settingsTabAgents:        { en:"Agents",              de:"Agenten",                ru:"Агенты",                zh:"代理",               es:"Agentes" },
settingsTabDesign:        { en:"Design",              de:"Design",                 ru:"Дизайн",                zh:"设计",               es:"Diseño" },
settingsTooltip:          { en:"Settings",            de:"Einstellungen",          ru:"Настройки",             zh:"设置",               es:"Configuración" },
settingsSubNamePlaceholder:{ en:"Name",               de:"Name",                   ru:"Название",              zh:"名称",               es:"Nombre" },
settingsSubEmailPlaceholder:{en:"Email (shown as label)",de:"Email (wird als Label angezeigt)",ru:"Email (как метка)",zh:"邮箱（显示为标签）",es:"Email (como etiqueta)" },
settingsSubPathPlaceholder:{ en:"Path",               de:"Pfad",                   ru:"Путь",                  zh:"路径",               es:"Ruta" },
settingsSubSave:          { en:"Save",                de:"Speichern",              ru:"Сохранить",             zh:"保存",               es:"Guardar" },
settingsSubCancel:        { en:"Cancel",              de:"Abbrechen",              ru:"Отмена",                zh:"取消",               es:"Cancelar" },
settingsSubAdd:           { en:"+ New Subscription",  de:"+ Neue Subscription",    ru:"+ Новая подписка",      zh:"+ 新建订阅",         es:"+ Nueva suscripción" },
settingsSubEdit:          { en:"Edit",                de:"Bearbeiten",             ru:"Редактировать",         zh:"编辑",               es:"Editar" },
settingsSubDelete:        { en:"Delete",              de:"Loeschen",               ru:"Удалить",               zh:"删除",               es:"Eliminar" },
settingsSubLoadFailed:    { en:"Could not load subscriptions",de:"Subscriptions konnten nicht geladen werden",ru:"Не удалось загрузить подписки",zh:"无法加载订阅",es:"No se pudieron cargar las suscripciones" },
settingsSubNone:          { en:"No subscriptions configured",de:"Keine Subscriptions konfiguriert",ru:"Нет настроенных подписок",zh:"暂无订阅配置",es:"No hay suscripciones configuradas" },
settingsSubUnnamed:       { en:"Unnamed",             de:"Unbenannt",              ru:"Без названия",          zh:"未命名",             es:"Sin nombre" },
settingsSubActivated:     { en:"Subscription activated",de:"Subscription aktiviert",ru:"Подписка активирована",zh:"订阅已激活",         es:"Suscripción activada" },
settingsSubDeactivated:   { en:"Subscription deactivated",de:"Subscription deaktiviert",ru:"Подписка деактивирована",zh:"订阅已停用",   es:"Suscripción desactivada" },
settingsSubDeleteConflict:{ en:"Cannot delete: agents assigned",de:"Kann nicht loeschen: Agents zugewiesen",ru:"Невозможно удалить: агенты назначены",zh:"无法删除：已分配代理",es:"No se puede eliminar: agentes asignados" },
settingsSubDeleteError:   { en:"Error deleting",      de:"Fehler beim Loeschen",   ru:"Ошибка удаления",       zh:"删除失败",           es:"Error al eliminar" },
settingsSubDeleted:       { en:"Subscription deleted", de:"Subscription geloescht", ru:"Подписка удалена",      zh:"订阅已删除",         es:"Suscripción eliminada" },
settingsSubUpdated:       { en:"Subscription updated", de:"Subscription aktualisiert",ru:"Подписка обновлена",  zh:"订阅已更新",         es:"Suscripción actualizada" },
settingsSubCreated:       { en:"Subscription created", de:"Subscription erstellt",  ru:"Подписка создана",      zh:"订阅已创建",         es:"Suscripción creada" },
settingsSubNameRequired:  { en:"Name is required",    de:"Name ist Pflicht",       ru:"Название обязательно",  zh:"名称为必填项",       es:"El nombre es obligatorio" },
settingsSubAgentsCount:   { en:"Agents",              de:"Agents",                 ru:"Агентов",               zh:"代理数",             es:"Agentes" },
settingsSubActive:        { en:"Active",              de:"Aktiv",                  ru:"Активна",               zh:"已激活",             es:"Activa" },
settingsSubInactive:      { en:"Inactive",            de:"Inaktiv",                ru:"Неактивна",             zh:"已停用",             es:"Inactiva" },
settingsShowInactive:     { en:"Show inactive",       de:"Inaktive zeigen",        ru:"Показать неактивных",   zh:"显示已停用",         es:"Mostrar inactivos" },
settingsDistributeBtn:    { en:"Distribute evenly",   de:"Gleichmaessig verteilen",ru:"Распределить равномерно",zh:"均匀分配",          es:"Distribuir equitativamente" },
settingsAgentTableAgent:  { en:"Agent",               de:"Agent",                  ru:"Агент",                 zh:"代理",               es:"Agente" },
settingsAgentTablePosition:{ en:"Position",           de:"Position",               ru:"Позиция",               zh:"职位",               es:"Posición" },
settingsAgentTableDescription:{ en:"Description",     de:"Beschreibung",           ru:"Описание",              zh:"描述",               es:"Descripción" },
settingsAgentTableEngine: { en:"Engine",              de:"Engine",                 ru:"Движок",                zh:"引擎",               es:"Motor" },
settingsAgentTableMode:   { en:"Mode",                de:"Modus",                  ru:"Режим",                 zh:"模式",               es:"Modo" },
settingsAgentTableSubscription:{ en:"Subscription",   de:"Subscription",           ru:"Подписка",              zh:"订阅",               es:"Suscripción" },
settingsAgentTableStatus: { en:"Status",              de:"Status",                 ru:"Статус",                zh:"状态",               es:"Estado" },
settingsAgentTableActions:{ en:"Actions",             de:"Aktionen",               ru:"Действия",              zh:"操作",               es:"Acciones" },
settingsAgentsLoadFailed: { en:"Could not load agents",de:"Agents konnten nicht geladen werden",ru:"Не удалось загрузить агентов",zh:"无法加载代理",es:"No se pudieron cargar los agentes" },
settingsAgentsNone:       { en:"No agents",           de:"Keine Agents",           ru:"Нет агентов",           zh:"暂无代理",           es:"Sin agentes" },
settingsAgentActive:      { en:"Active",              de:"Aktiv",                  ru:"Активен",               zh:"活跃",               es:"Activo" },
settingsAgentInactive:    { en:"Inactive",            de:"Inaktiv",                ru:"Неактивен",             zh:"停用",               es:"Inactivo" },
settingsModeNormal:       { en:"Normal",              de:"Normal",                 ru:"Обычный",               zh:"普通",               es:"Normal" },
settingsModeAuto:         { en:"Auto",                de:"Auto",                   ru:"Авто",                  zh:"自动",               es:"Auto" },
settingsModeStandby:      { en:"Standby",             de:"Standby",                ru:"Ожидание",              zh:"待机",               es:"Espera" },
settingsSubAssigned:      { en:"Subscription assigned",de:"Subscription zugewiesen",ru:"Подписка назначена",   zh:"订阅已分配",         es:"Suscripción asignada" },
settingsModeChanged:      { en:"Mode changed",        de:"Modus geaendert",        ru:"Режим изменён",         zh:"模式已更改",         es:"Modo cambiado" },
settingsNoSubscriptions:  { en:"No subscriptions available",de:"Keine Subscriptions vorhanden",ru:"Нет доступных подписок",zh:"暂无可用订阅",es:"No hay suscripciones disponibles" },
settingsDistributed:      { en:"Agents distributed",  de:"Agents verteilt",        ru:"Агенты распределены",   zh:"代理已分配",         es:"Agentes distribuidos" },
settingsThemeWarm:        { en:"Warm",                de:"Warm",                   ru:"Тёплая",                zh:"暖色",               es:"Cálido" },
settingsThemeLight:       { en:"Light",               de:"Hell",                   ru:"Светлая",               zh:"浅色",               es:"Claro" },
settingsThemeRose:        { en:"Rosé",                de:"Rosé",                   ru:"Розовая",               zh:"玫瑰",               es:"Rosé" },
settingsThemeDark:        { en:"Dark",                de:"Dunkel",                 ru:"Тёмная",                zh:"深色",               es:"Oscuro" },
settingsLanguageLabel:    { en:"Language",            de:"Sprache",                ru:"Язык",                  zh:"语言",               es:"Idioma" },

// ─── BOARD HEADERS ───
boardManagement:          { en:"Management Board",    de:"Management-Board",       ru:"Правление",             zh:"管理面板",           es:"Panel de gestión" },
boardTeam:                { en:"Team Board",          de:"Team-Board",             ru:"Командная доска",       zh:"团队面板",           es:"Panel de equipo" },
boardConnectionLost:      { en:"Connection lost",     de:"Verbindung verloren",    ru:"Соединение потеряно",   zh:"连接已断开",         es:"Conexión perdida" },

// ─── CHAT ───
chatPlaceholderAgent:     { en:"Message to agent...", de:"Nachricht an Agent...",  ru:"Сообщение агенту...",   zh:"发送消息给代理...",   es:"Mensaje al agente..." },
chatPlaceholderTeam:      { en:"Message to team...",  de:"Nachricht ans Team...",  ru:"Сообщение команде...",  zh:"发送消息给团队...",   es:"Mensaje al equipo..." },
chatSendAria:             { en:"Send message",        de:"Nachricht senden",       ru:"Отправить сообщение",   zh:"发送消息",           es:"Enviar mensaje" },
chatAttachTitle:          { en:"Attach",              de:"Anhaengen",              ru:"Прикрепить",            zh:"附件",               es:"Adjuntar" },
chatAttachRemove:         { en:"Remove",              de:"Entfernen",              ru:"Удалить",               zh:"移除",               es:"Eliminar" },
chatAllManagers:          { en:"All Managers",        de:"Alle Manager",           ru:"Все менеджеры",         zh:"所有管理者",         es:"Todos los gerentes" },
chatAll:                  { en:"All",                 de:"Alle",                   ru:"Все",                   zh:"全部",               es:"Todos" },
chatSendFailed:           { en:"Send failed: ",       de:"Senden fehlgeschlagen: ",ru:"Ошибка отправки: ",     zh:"发送失败：",         es:"Error al enviar: " },
chatSendFailedUnknown:    { en:"Unknown error",       de:"Unbekannter Fehler",     ru:"Неизвестная ошибка",    zh:"未知错误",           es:"Error desconocido" },
chatSendFailedServer:     { en:"Send failed — server unreachable",de:"Senden fehlgeschlagen — Server nicht erreichbar",ru:"Ошибка — сервер недоступен",zh:"发送失败——服务器不可达",es:"Error — servidor inaccesible" },
chatWsBanner:             { en:"Connection interrupted — messages not updating live",de:"Verbindung unterbrochen — Nachrichten werden nicht live aktualisiert",ru:"Соединение прервано — сообщения не обновляются",zh:"连接中断——消息未实时更新",es:"Conexión interrumpida — mensajes no se actualizan en vivo" },
chatReplyLabel:           { en:"Reply",               de:"Antwort",                ru:"Ответ",                 zh:"回复",               es:"Respuesta" },
chatReplyTo:              { en:"Reply to",            de:"Antwort an",             ru:"Ответ для",             zh:"回复给",             es:"Responder a" },
chatReplyClose:           { en:"Close",               de:"Schliessen",             ru:"Закрыть",               zh:"关闭",               es:"Cerrar" },
chatReplySend:            { en:"Send",                de:"Senden",                 ru:"Отправить",             zh:"发送",               es:"Enviar" },
chatCopyBtn:              { en:"Copy",                de:"Kopieren",               ru:"Копировать",            zh:"复制",               es:"Copiar" },
chatReplyBtn:             { en:"Reply",               de:"Antworten",              ru:"Ответить",              zh:"回复",               es:"Responder" },
chatFileDefault:          { en:"File",                de:"Datei",                  ru:"Файл",                  zh:"文件",               es:"Archivo" },
chatTyping:               { en:"typing\u2026",        de:"tippt\u2026",            ru:"печатает\u2026",        zh:"正在输入\u2026",     es:"escribiendo\u2026" },
chatTimeJustNow:          { en:"just now",            de:"gerade eben",            ru:"только что",            zh:"刚刚",               es:"ahora mismo" },
chatTimeMinAgo:           { en:"{n} min ago",         de:"vor {n} Min",            ru:"{n} мин назад",         zh:"{n}分钟前",          es:"hace {n} min" },
chatSkipToContent:        { en:"Skip to content",     de:"Zum Inhalt springen",    ru:"Перейти к содержимому", zh:"跳转到内容",         es:"Ir al contenido" },

// ─── APPROVAL GATE ───
approvalBadgeTitle:       { en:"Approvals",           de:"Genehmigungen",          ru:"Утверждения",           zh:"审批",               es:"Aprobaciones" },
approvalPanelTitle:       { en:"Approvals",           de:"Genehmigungen",          ru:"Утверждения",           zh:"审批",               es:"Aprobaciones" },
approvalPanelCountSuffix: { en:"open",                de:"offen",                  ru:"открыто",               zh:"待处理",             es:"pendientes" },
approvalPanelEmpty:       { en:"No pending approvals",de:"Keine offenen Genehmigungen",ru:"Нет ожидающих утверждений",zh:"暂无待审批项",es:"Sin aprobaciones pendientes" },
approvalHistoryTitle:     { en:"Past Decisions",      de:"Vergangene Entscheidungen",ru:"Прошлые решения",     zh:"历史决策",           es:"Decisiones pasadas" },
approvalHistoryEmpty:     { en:"No decisions yet",    de:"Noch keine Entscheidungen",ru:"Решений пока нет",    zh:"暂无决策记录",       es:"Aún sin decisiones" },
approvalToastApprove:     { en:"OK",                  de:"OK",                     ru:"ОК",                    zh:"确定",               es:"OK" },
approvalToastDeny:        { en:"No",                  de:"Nein",                   ru:"Нет",                   zh:"拒绝",               es:"No" },
approvalToastDetails:     { en:"Details",             de:"Details",                ru:"Подробнее",             zh:"详情",               es:"Detalles" },
approvalCardApprove:      { en:"Approve",             de:"Genehmigen",             ru:"Утвердить",             zh:"批准",               es:"Aprobar" },
approvalCardDeny:         { en:"Deny",                de:"Ablehnen",               ru:"Отклонить",             zh:"拒绝",               es:"Rechazar" },
approvalCardApproveEdited:{ en:"Send as edited",      de:"Als editiert senden",    ru:"Отправить с правками",  zh:"发送编辑版",         es:"Enviar como editado" },
approvalCardWho:          { en:"wants to",            de:"will",                   ru:"хочет",                 zh:"想要",               es:"quiere" },
approvalCardTo:           { en:"To: ",                de:"An: ",                   ru:"Кому: ",                zh:"收件人：",           es:"Para: " },
approvalCardSubject:      { en:"Subject",             de:"Betreff",                ru:"Тема",                  zh:"主题",               es:"Asunto" },
approvalCardContent:      { en:"Content",             de:"Inhalt",                 ru:"Содержание",            zh:"内容",               es:"Contenido" },
approvalFeedbackApproved: { en:"Approved — executing",de:"Genehmigt — wird ausgefuehrt",ru:"Утверждено — выполняется",zh:"已批准——执行中",es:"Aprobado — ejecutando" },
approvalFeedbackDenied:   { en:"Denied — agent notified",de:"Abgelehnt — Agent informiert",ru:"Отклонено — агент уведомлён",zh:"已拒绝——代理已通知",es:"Rechazado — agente notificado" },
approvalFeedbackExpired:  { en:"Expired — not executed",de:"Abgelaufen — nicht ausgefuehrt",ru:"Истекло — не выполнено",zh:"已过期——未执行",es:"Expirado — no ejecutado" },
approvalFeedbackError:    { en:"Could not save change",de:"Aenderung konnte nicht gespeichert werden",ru:"Не удалось сохранить",zh:"无法保存更改",es:"No se pudo guardar el cambio" },
approvalActionEmailSend:  { en:"Send email",          de:"Email senden",           ru:"Отправить email",       zh:"发送邮件",           es:"Enviar email" },
approvalActionPhoneCall:  { en:"Phone call",          de:"Anrufen",                ru:"Позвонить",             zh:"拨打电话",           es:"Llamar" },
approvalActionSlackSend:  { en:"Send Slack message",  de:"Slack-Nachricht senden", ru:"Отправить в Slack",     zh:"发送Slack消息",      es:"Enviar mensaje de Slack" },
approvalActionTelegramSend:{ en:"Send Telegram",      de:"Telegram senden",        ru:"Отправить в Telegram",  zh:"发送Telegram",       es:"Enviar Telegram" },
approvalActionWhatsappSend:{ en:"Send WhatsApp",      de:"WhatsApp senden",        ru:"Отправить WhatsApp",    zh:"发送WhatsApp",       es:"Enviar WhatsApp" },
approvalActionWhatsappVoice:{ en:"Send WhatsApp voice",de:"WhatsApp Voice senden", ru:"Отправить голосовое WhatsApp", zh:"发送WhatsApp语音", es:"Enviar voz por WhatsApp" },
approvalActionFileDelete: { en:"Delete file",         de:"Datei loeschen",         ru:"Удалить файл",          zh:"删除文件",           es:"Eliminar archivo" },
approvalActionTradeExecute:{ en:"Execute trade",      de:"Trade ausfuehren",       ru:"Выполнить сделку",      zh:"执行交易",           es:"Ejecutar operación" },
approvalActionPayment:    { en:"Trigger payment",     de:"Zahlung ausloesen",      ru:"Выполнить платёж",      zh:"触发付款",           es:"Ejecutar pago" },
approvalActionBrowserLogin:{ en:"Website login",      de:"Website-Login",          ru:"Вход на сайт",          zh:"网站登录",           es:"Inicio de sesión" },

// ─── TEAMS PANEL ───
teamsPanelTitle:          { en:"My Teams",            de:"Meine Teams",            ru:"Мои команды",           zh:"我的团队",           es:"Mis equipos" },
teamsPanelAdd:            { en:"+ New Team",          de:"+ Neues Team",           ru:"+ Новая команда",       zh:"+ 新建团队",         es:"+ Nuevo equipo" },
teamsPanelLoadFailed:     { en:"Could not load teams.",de:"Teams konnten nicht geladen werden.",ru:"Не удалось загрузить команды.",zh:"无法加载团队。",es:"No se pudieron cargar los equipos." },
teamsPanelEmpty:          { en:"No teams yet.",       de:"Keine Teams vorhanden.", ru:"Нет команд.",           zh:"暂无团队。",         es:"Sin equipos." },
teamsPanelEmptyHint:      { en:'Create a team with "+ New Team".',de:'Erstelle ein Team mit "+ Neues Team".',ru:'Создайте команду через "+ Новая команда".',zh:'点击"+ 新建团队"创建团队。',es:'Crea un equipo con "+ Nuevo equipo".' },
teamsPanelLoading:        { en:"Loading...",          de:"Laden...",               ru:"Загрузка...",           zh:"加载中...",           es:"Cargando..." },
teamsCardOnline:          { en:"online",              de:"online",                 ru:"онлайн",                zh:"在线",               es:"en línea" },
teamsCardLead:            { en:"Lead: ",              de:"Leiter: ",               ru:"Руководитель: ",        zh:"负责人：",           es:"Líder: " },
teamsDetailTabMembers:    { en:"Members",             de:"Mitglieder",             ru:"Участники",             zh:"成员",               es:"Miembros" },
teamsDetailTabTasks:      { en:"Tasks",               de:"Aufgaben",               ru:"Задачи",                zh:"任务",               es:"Tareas" },
teamsDetailMembersTitle:  { en:"Team Members",        de:"Team-Mitglieder",        ru:"Участники команды",     zh:"团队成员",           es:"Miembros del equipo" },
teamsDetailScope:         { en:"Scope",               de:"Scope",                  ru:"Область",               zh:"范围",               es:"Alcance" },
teamsDetailBadgeLead:     { en:"Lead",                de:"Lead",                   ru:"Лид",                   zh:"负责人",             es:"Líder" },

// ─── TEAM WIZARD ───
wizardTitle:              { en:"Create New Team",     de:"Neues Team erstellen",   ru:"Создать команду",       zh:"创建新团队",         es:"Crear nuevo equipo" },
wizardStep1Label:         { en:"Step 1 of 3 — Name",  de:"Schritt 1 von 3 — Name", ru:"Шаг 1 из 3 — Название", zh:"第1步/共3步——名称",  es:"Paso 1 de 3 — Nombre" },
wizardStep2Label:         { en:"Step 2 of 3 — Team",  de:"Schritt 2 von 3 — Team", ru:"Шаг 2 из 3 — Команда",  zh:"第2步/共3步——团队",  es:"Paso 2 de 3 — Equipo" },
wizardStep3Label:         { en:"Step 3 of 3 — Review",de:"Schritt 3 von 3 — Pruefen",ru:"Шаг 3 из 3 — Проверка",zh:"第3步/共3步——确认",es:"Paso 3 de 3 — Revisar" },
wizardTeamName:           { en:"Team Name",           de:"Teamname",               ru:"Название команды",      zh:"团队名称",           es:"Nombre del equipo" },
wizardTeamNamePlaceholder:{ en:"e.g. Marketing, Development...",de:"z.B. Marketing, Entwicklung...",ru:"напр. Маркетинг, Разработка...",zh:"例如：市场部、开发部...",es:"p.ej. Marketing, Desarrollo..." },
wizardDescription:        { en:"Description (optional)",de:"Beschreibung (optional)",ru:"Описание (необязательно)",zh:"描述（可选）",    es:"Descripción (opcional)" },
wizardDescPlaceholder:    { en:"What does this team do?",de:"Was macht dieses Team?",ru:"Чем занимается команда?",zh:"这个团队做什么？",es:"¿Qué hace este equipo?" },
wizardTeamLead:           { en:"Team Lead",           de:"Teamleitung",            ru:"Руководитель",          zh:"团队负责人",         es:"Líder del equipo" },
wizardMembers:            { en:"Members",             de:"Mitglieder",             ru:"Участники",             zh:"成员",               es:"Miembros" },
wizardBack:               { en:"Back",                de:"Zurueck",                ru:"Назад",                 zh:"上一步",             es:"Atrás" },
wizardNext:               { en:"Next",                de:"Weiter",                 ru:"Далее",                 zh:"下一步",             es:"Siguiente" },
wizardCreate:             { en:"Create Team",         de:"Team erstellen",         ru:"Создать команду",       zh:"创建团队",           es:"Crear equipo" },
wizardCreating:           { en:"Creating...",         de:"Wird erstellt...",       ru:"Создание...",           zh:"创建中...",           es:"Creando..." },
wizardErrorNoName:        { en:"Please enter a team name.",de:"Bitte gib einen Teamnamen ein.",ru:"Введите название команды.",zh:"请输入团队名称。",es:"Introduce un nombre de equipo." },
wizardErrorNoLead:        { en:"Please select a team lead.",de:"Bitte waehle eine Teamleitung.",ru:"Выберите руководителя.",zh:"请选择团队负责人。",es:"Selecciona un líder de equipo." },
wizardErrorNoMembers:     { en:"Please select at least one member.",de:"Bitte waehle mindestens ein Mitglied.",ru:"Выберите хотя бы одного участника.",zh:"请至少选择一名成员。",es:"Selecciona al menos un miembro." },
wizardErrorCreateFailed:  { en:"Error creating (Status ",de:"Fehler beim Erstellen (Status ",ru:"Ошибка создания (Статус ",zh:"创建失败（状态码 ",es:"Error al crear (Estado " },
wizardErrorNetwork:       { en:"Network error — please try again.",de:"Netzwerkfehler — bitte erneut versuchen.",ru:"Ошибка сети — попробуйте снова.",zh:"网络错误——请重试。",es:"Error de red — inténtalo de nuevo." },
wizardCreated:            { en:"Team created",        de:"Team erstellt",          ru:"Команда создана",       zh:"团队已创建",         es:"Equipo creado" },
wizardCreatedDesc:        { en:"was successfully created.",de:"wurde erfolgreich erstellt.",ru:"успешно создана.",zh:"创建成功。",         es:"se creó correctamente." },
wizardSummaryName:        { en:"Team Name",           de:"Teamname",               ru:"Название",              zh:"名称",               es:"Nombre" },
wizardSummaryDesc:        { en:"Description",         de:"Beschreibung",           ru:"Описание",              zh:"描述",               es:"Descripción" },
wizardSummaryLead:        { en:"Lead",                de:"Leitung",                ru:"Руководитель",          zh:"负责人",             es:"Líder" },
wizardSummaryMembers:     { en:"Members",             de:"Mitglieder",             ru:"Участники",             zh:"成员",               es:"Miembros" },
wizardSummaryCount:       { en:"Count",               de:"Anzahl",                 ru:"Количество",            zh:"人数",               es:"Cantidad" },

// ─── TASK CREATE MODAL ───
taskCreateTitle:          { en:"New Task",            de:"Neue Aufgabe",           ru:"Новая задача",          zh:"新建任务",           es:"Nueva tarea" },
taskCreateTitleLabel:     { en:"What needs to be done?",de:"Was soll gemacht werden?",ru:"Что нужно сделать?",  zh:"需要做什么？",       es:"¿Qué hay que hacer?" },
taskCreateTitlePlaceholder:{ en:"e.g. Implement activity check...",de:"z.B. Activity-Check implementieren...",ru:"напр. Реализовать проверку...",zh:"例如：实现活动检查...",es:"p.ej. Implementar verificación..." },
taskCreateDescLabel:      { en:"Details (optional)",  de:"Details (optional)",     ru:"Подробности (необязательно)",zh:"详情（可选）",    es:"Detalles (opcional)" },
taskCreateDescPlaceholder:{ en:"Describe what exactly needs to be done...",de:"Beschreibe was genau getan werden soll...",ru:"Опишите что именно нужно сделать...",zh:"描述具体需要做什么...",es:"Describe qué hay que hacer exactamente..." },
taskCreateAssignLabel:    { en:"Assign to",           de:"Zuweisen an",            ru:"Назначить",             zh:"分配给",             es:"Asignar a" },
taskCreateAssignDefault:  { en:"Unassigned (assign later)",de:"Noch offen (spaeter zuweisen)",ru:"Не назначено (позже)",zh:"暂不分配（稍后指定）",es:"Sin asignar (asignar después)" },
taskCreatePriorityLabel:  { en:"Priority",            de:"Prioritaet",             ru:"Приоритет",             zh:"优先级",             es:"Prioridad" },
taskCreatePriorityNormal: { en:"Normal",              de:"Normal",                 ru:"Обычный",               zh:"普通",               es:"Normal" },
taskCreatePriorityHigh:   { en:"High",                de:"Hoch",                   ru:"Высокий",               zh:"高",                 es:"Alta" },
taskCreatePriorityCritical:{ en:"Critical",           de:"Kritisch",               ru:"Критический",           zh:"紧急",               es:"Crítica" },
taskCreateCancel:         { en:"Cancel",              de:"Abbrechen",              ru:"Отмена",                zh:"取消",               es:"Cancelar" },
taskCreateSubmit:         { en:"Create",              de:"Erstellen",              ru:"Создать",               zh:"创建",               es:"Crear" },
taskCreateSubmitting:     { en:"Creating...",         de:"Wird erstellt...",       ru:"Создание...",           zh:"创建中...",           es:"Creando..." },
taskCreateErrorNoTitle:   { en:"Please enter a title.",de:"Bitte gib einen Titel ein.",ru:"Введите заголовок.",  zh:"请输入标题。",       es:"Introduce un título." },
taskCreateSuccess:        { en:"Task created",        de:"Aufgabe erstellt",       ru:"Задача создана",        zh:"任务已创建",         es:"Tarea creada" },

// ─── KANBAN / TASK BOARD ───
kanbanStateOpen:          { en:"Open",                de:"Offen",                  ru:"Открыто",               zh:"待处理",             es:"Abierto" },
kanbanStateInProgress:    { en:"In Progress",         de:"In Arbeit",              ru:"В работе",              zh:"进行中",             es:"En progreso" },
kanbanStateDone:          { en:"Done",                de:"Fertig",                 ru:"Готово",                zh:"已完成",             es:"Hecho" },
kanbanStateFailed:        { en:"Failed",              de:"Fehlgeschlagen",         ru:"Ошибка",                zh:"失败",               es:"Fallido" },
kanbanNoTasks:            { en:"No tasks",            de:"Keine Aufgaben",         ru:"Нет задач",             zh:"暂无任务",           es:"Sin tareas" },
kanbanShowMore:           { en:"show more",           de:"weitere anzeigen",       ru:"показать ещё",          zh:"显示更多",           es:"mostrar más" },
kanbanAddTask:            { en:"+ New Task",          de:"+ Neue Aufgabe",         ru:"+ Новая задача",        zh:"+ 新建任务",         es:"+ Nueva tarea" },
kanbanCompleted:          { en:"Completed",           de:"Abgeschlossen",          ru:"Завершено",             zh:"已完成",             es:"Completado" },
kanbanUnassigned:         { en:"Unassigned",          de:"Noch nicht zugewiesen",  ru:"Не назначено",          zh:"未分配",             es:"Sin asignar" },
kanbanNoTitle:            { en:"No title",            de:"Ohne Titel",             ru:"Без заголовка",         zh:"无标题",             es:"Sin título" },
kanbanPriorityHigh:       { en:"High",                de:"Hoch",                   ru:"Высокий",               zh:"高",                 es:"Alta" },
kanbanPriorityCritical:   { en:"Critical",            de:"Kritisch",               ru:"Критический",           zh:"紧急",               es:"Crítica" },
kanbanLoadingTasks:       { en:"Loading tasks...",    de:"Aufgaben laden...",      ru:"Загрузка задач...",     zh:"加载任务中...",       es:"Cargando tareas..." },
kanbanLoadError:          { en:"Error loading tasks.",de:"Fehler beim Laden der Aufgaben.",ru:"Ошибка загрузки задач.",zh:"加载任务失败。",es:"Error al cargar las tareas." },
kanbanTimeJustNow:        { en:"just now",            de:"gerade eben",            ru:"только что",            zh:"刚刚",               es:"ahora mismo" },
kanbanTimeMinAgo:         { en:"{n} min ago",         de:"vor {n} Min",            ru:"{n} мин назад",         zh:"{n}分钟前",          es:"hace {n} min" },
kanbanTimeHoursAgo:       { en:"{n}h ago",            de:"vor {n}h",               ru:"{n}ч назад",            zh:"{n}小时前",          es:"hace {n}h" },
kanbanTimeDaysAgo:        { en:"{n}d ago",            de:"vor {n}d",               ru:"{n}д назад",            zh:"{n}天前",            es:"hace {n}d" },

// ─── ORG CHART ───
orgPanelTitle:            { en:"Team",                de:"Team",                   ru:"Команда",               zh:"团队",               es:"Equipo" },
orgOnlineCount:           { en:"online",              de:"online",                 ru:"онлайн",                zh:"在线",               es:"en línea" },

// ─── STATUS LABELS ───
statusOnline:             { en:"Online",              de:"Online",                 ru:"Онлайн",                zh:"在线",               es:"En línea" },
statusWaiting:            { en:"Waiting",             de:"Wartet",                 ru:"Ожидает",               zh:"等待中",             es:"Esperando" },
statusError:              { en:"Error",               de:"Fehler",                 ru:"Ошибка",                zh:"错误",               es:"Error" },
statusOffline:            { en:"Offline",             de:"Offline",                ru:"Не в сети",             zh:"离线",               es:"Desconectado" },
statusStale:              { en:"Not responding",      de:"Reagiert nicht",         ru:"Не отвечает",           zh:"无响应",             es:"No responde" },
statusDeactivated:        { en:"Deactivated",         de:"Deaktiviert",            ru:"Деактивирован",         zh:"已停用",             es:"Desactivado" },

// ─── AGENT TOGGLE ───
agentToggleActive:        { en:"Active",              de:"Aktiv",                  ru:"Активен",               zh:"活跃",               es:"Activo" },
agentTogglePaused:        { en:"Paused",              de:"Pausiert",               ru:"На паузе",              zh:"已暂停",             es:"Pausado" },
agentTogglePauseBtn:      { en:"Pause",               de:"Pausieren",              ru:"Пауза",                zh:"暂停",               es:"Pausar" },
agentToggleActivateBtn:   { en:"Activate",            de:"Aktivieren",             ru:"Активировать",          zh:"激活",               es:"Activar" },
agentToggleCancelBtn:     { en:"Cancel",              de:"Abbrechen",              ru:"Отмена",                zh:"取消",               es:"Cancelar" },
agentToggleWait:          { en:"Please wait...",      de:"Bitte warten...",        ru:"Подождите...",          zh:"请稍候...",           es:"Espere..." },
agentToggleActivatedMsg:  { en:"is active again",     de:"ist wieder aktiv",       ru:"снова активен",         zh:"已重新激活",         es:"está activo de nuevo" },
agentTogglePausedMsg:     { en:"was paused",          de:"wurde pausiert",         ru:"поставлен на паузу",    zh:"已暂停",             es:"fue pausado" },

// ─── TASK TOASTS ───
toastTaskClaimed:         { en:"Task claimed",        de:"Aufgabe uebernommen",    ru:"Задача принята",        zh:"任务已认领",         es:"Tarea reclamada" },
toastTaskDone:            { en:"Task completed",      de:"Aufgabe abgeschlossen",  ru:"Задача завершена",      zh:"任务已完成",         es:"Tarea completada" },
toastTaskFailed:          { en:"Task failed",         de:"Aufgabe fehlgeschlagen",  ru:"Задача провалена",     zh:"任务失败",           es:"Tarea fallida" },
toastScopeLock:           { en:"File conflict",       de:"Datei-Konflikt",         ru:"Конфликт файла",        zh:"文件冲突",           es:"Conflicto de archivo" },
toastAgentStale:          { en:"not responding",      de:"reagiert nicht",         ru:"не отвечает",           zh:"无响应",             es:"no responde" },
toastLeadOffline:         { en:"Team lead offline",   de:"Team-Lead offline",      ru:"Руководитель не в сети",zh:"团队负责人离线",     es:"Líder de equipo desconectado" },

// ─── MISC ───
pageTitle:                { en:"Bridge – Chat",       de:"Bridge – Chat Layout",   ru:"Bridge – Чат",          zh:"Bridge – 聊天",      es:"Bridge – Chat" },
systemLabel:              { en:"System",              de:"System",                 ru:"Система",               zh:"系统",               es:"Sistema" },
noDescription:            { en:"—",                   de:"—",                      ru:"—",                     zh:"—",                  es:"—" },
errorPrefix:              { en:"Error: ",             de:"Fehler: ",               ru:"Ошибка: ",              zh:"错误：",             es:"Error: " },
confirm:                  { en:"Are you sure?",       de:"Bist du sicher?",        ru:"Вы уверены?",           zh:"确定吗？",           es:"¿Estás seguro?" },
yes:                      { en:"Yes",                 de:"Ja",                     ru:"Да",                    zh:"是",                 es:"Sí" },
no:                       { en:"No",                  de:"Nein",                   ru:"Нет",                   zh:"否",                 es:"No" },
ok:                       { en:"OK",                  de:"OK",                     ru:"ОК",                    zh:"确定",               es:"OK" },
cancel:                   { en:"Cancel",              de:"Abbrechen",              ru:"Отмена",                zh:"取消",               es:"Cancelar" },
save:                     { en:"Save",                de:"Speichern",              ru:"Сохранить",             zh:"保存",               es:"Guardar" },
close:                    { en:"Close",               de:"Schliessen",             ru:"Закрыть",               zh:"关闭",               es:"Cerrar" },
loading:                  { en:"Loading...",          de:"Laden...",               ru:"Загрузка...",           zh:"加载中...",           es:"Cargando..." },
networkError:             { en:"Network error",       de:"Netzwerkfehler",         ru:"Ошибка сети",           zh:"网络错误",           es:"Error de red" },

};

// ─── i18n ENGINE ───

const BRIDGE_LANGUAGES = [
  { code:'en', label:'English' },
  { code:'de', label:'Deutsch' },
  { code:'ru', label:'Русский' },
  { code:'zh', label:'中文' },
  { code:'es', label:'Español' },
];

let _bridgeLang = localStorage.getItem('bridge_language') || 'en';

function t(key, params) {
  const entry = BRIDGE_I18N[key];
  if (!entry) return key;
  let str = entry[_bridgeLang] || entry['en'] || key;
  if (params) {
    Object.keys(params).forEach(k => {
      str = str.replace(new RegExp('\\{' + k + '\\}', 'g'), params[k]);
    });
  }
  return str;
}

function setLanguage(lang) {
  if (!BRIDGE_LANGUAGES.some(l => l.code === lang)) return;
  _bridgeLang = lang;
  localStorage.setItem('bridge_language', lang);
  document.documentElement.lang = lang;
  applyTranslations();
}

function getLanguage() {
  return _bridgeLang;
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const attr = el.dataset.i18nAttr;
    if (attr === 'placeholder') {
      el.placeholder = t(key);
    } else if (attr === 'title') {
      el.title = t(key);
    } else if (attr === 'aria-label') {
      el.setAttribute('aria-label', t(key));
    } else {
      el.textContent = t(key);
    }
  });
}
