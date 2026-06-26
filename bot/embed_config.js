// ModForge – ZENTRALE EMBED KONFIGURATION (VOLLSTÄNDIG) – Node.js
const { EmbedBuilder } = require('discord.js');
const { modernizeEmbed } = require('./utils');

const COLORS = {
  primary: 0x5865F2,
  success: 0x22C55E,
  warning: 0xF59E0B,
  danger: 0xEF4444,
  info: 0x3B82F6,
  purple: 0x8B5CF6,
  pink: 0xEC4899,
  teal: 0x14B8A6,
  dark: 0x1F2937,
  gold: 0xFBBF24,
};

function mention(user) { return user?.toString?.() || (user?.id ? `<@${user.id}>` : String(user || 'Unbekannt')); }
function avatarUrl(user) { return user?.displayAvatarURL?.() || user?.avatarURL?.() || user?.defaultAvatarURL || null; }
function nameOf(obj) { return obj?.name || obj?.tag || obj?.username || String(obj || ''); }

function getEmbed(name, kwargs = {}) {
  const data = { ...(kwargs || {}) };
  const func = EMBEDS[name];
  const embed = func ? func(data) : new EmbedBuilder()
    .setTitle('❌ Embed nicht gefunden')
    .setDescription(`Das Embed \`${name}\` ist nicht definiert.`)
    .setColor(COLORS.danger);
  return modernizeEmbed(embed, { author: data.author || data.executor || data.mod || data.user, guild: data.guild });
}

function embed_welcome(kwargs) { const { guild, user } = kwargs; const e = new EmbedBuilder().setTitle('👋 Willkommen!').setDescription(`Schön, dass du da bist ${mention(user)}!`).setColor(COLORS.success).setFooter({ text: `${nameOf(guild)}` }).setTimestamp(new Date()); const av = avatarUrl(user); if (av) e.setThumbnail(av); return e; }
function embed_leave(kwargs) { const { guild, user } = kwargs; return new EmbedBuilder().setTitle('👋 Auf Wiedersehen').setDescription(`${user} hat den Server verlassen.`).setColor(COLORS.dark).setFooter({ text: `${nameOf(guild)}` }); }
function embed_onboarding() { return new EmbedBuilder().setTitle('🎉 Willkommen!').setDescription('Bitte verifiziere dich, um vollen Zugriff zu erhalten.').setColor(COLORS.primary).setFooter({ text: 'Onboarding' }); }
function embed_verification_panel() { return new EmbedBuilder().setTitle('✅ Verification').setDescription('Klicke auf den Button, um dich zu verifizieren.').setColor(COLORS.primary).setFooter({ text: 'Verification System' }); }
function embed_verification_success(kwargs) { const { user } = kwargs; return new EmbedBuilder().setTitle('✅ Verifiziert!').setDescription(`${mention(user)} wurde erfolgreich verifiziert.`).setColor(COLORS.success); }
function embed_verification_failed() { return new EmbedBuilder().setTitle('❌ Verification fehlgeschlagen').setDescription('Bitte versuche es erneut.').setColor(COLORS.danger); }
function embed_ticket_panel() { return new EmbedBuilder().setTitle('🎫 Ticket System').setDescription('Wähle eine Kategorie aus, um ein Ticket zu öffnen.').setColor(COLORS.info).setFooter({ text: 'Ticket System • ModForge' }); }
function embed_ticket_created(kwargs) { const ticket_id = kwargs.ticket_id; const category = kwargs.category || 'Support'; return new EmbedBuilder().setTitle('🎫 Ticket erstellt').setDescription(`Dein Ticket **#${ticket_id}** wurde erstellt.`).setColor(COLORS.success).addFields({ name: 'Kategorie', value: String(category) }).setFooter({ text: 'Ticket System' }); }
function embed_ticket_closed(kwargs) { return new EmbedBuilder().setTitle('🔒 Ticket geschlossen').setDescription(`Ticket **#${kwargs.ticket_id}** wurde von ${kwargs.closed_by} geschlossen.`).setColor(COLORS.dark); }
function embed_ticket_transcript(kwargs) { return new EmbedBuilder().setTitle('📜 Transcript').setDescription(`Transcript für Ticket #${kwargs.ticket_id}`).setColor(COLORS.purple).setFooter({ text: 'Ticket System' }); }
function embed_ticket_claimed(kwargs) { return new EmbedBuilder().setTitle('🙋 Ticket übernommen').setDescription(`Ticket #${kwargs.ticket_id} wurde von ${kwargs.staff} übernommen.`).setColor(COLORS.info); }
function embed_tempvoice_panel() { return new EmbedBuilder().setTitle('🔊 TempVoice').setDescription('Klicke auf den Button, um einen eigenen Voice-Kanal zu erstellen.').setColor(COLORS.purple).setFooter({ text: 'TempVoice System' }); }
function embed_tempvoice_created(kwargs) { return new EmbedBuilder().setTitle('🔊 TempVoice erstellt').setDescription(`${mention(kwargs.owner)} hat den Kanal ${mention(kwargs.channel)} erstellt.`).setColor(COLORS.success); }
function embed_tempvoice_deleted(kwargs) { return new EmbedBuilder().setTitle('🗑️ TempVoice gelöscht').setDescription(`Der Kanal **${kwargs.channel_name}** wurde gelöscht.`).setColor(COLORS.dark); }
function embed_tempvoice_owner_action(kwargs) { return new EmbedBuilder().setTitle(`🔧 ${kwargs.action || 'Aktion'}`).setDescription('Die Aktion wurde ausgeführt.').setColor(COLORS.info); }
function embed_ban(kwargs) { const user = kwargs.user; const mod = kwargs.mod; const reason = kwargs.reason || 'Kein Grund'; return new EmbedBuilder().setTitle('🔨 Ban').setDescription(`${mention(user)} wurde gebannt.`).setColor(COLORS.danger).addFields({ name: 'Moderator', value: String(mod), inline: true }, { name: 'Grund', value: String(reason), inline: false }).setFooter({ text: 'Moderation' }); }
function embed_kick(kwargs) { const user = kwargs.user; const mod = kwargs.mod; const reason = kwargs.reason || 'Kein Grund'; return new EmbedBuilder().setTitle('👢 Kick').setDescription(`${mention(user)} wurde gekickt.`).setColor(COLORS.warning).addFields({ name: 'Moderator', value: String(mod) }, { name: 'Grund', value: String(reason) }); }
function embed_mute(kwargs) { const user = kwargs.user; const duration = kwargs.duration || 'Unbekannt'; const reason = kwargs.reason || 'Kein Grund'; return new EmbedBuilder().setTitle('🔇 Mute').setDescription(`${mention(user)} wurde stummgeschaltet.`).setColor(COLORS.purple).addFields({ name: 'Dauer', value: String(duration) }, { name: 'Grund', value: String(reason) }); }
function embed_warn(kwargs) { const user = kwargs.user; const reason = kwargs.reason || 'Kein Grund'; return new EmbedBuilder().setTitle('⚠️ Warn').setDescription(`${mention(user)} wurde verwarnt.`).setColor(COLORS.warning).addFields({ name: 'Grund', value: String(reason) }); }
function embed_case(kwargs) { const action = String(kwargs.action || 'unknown').toUpperCase(); const user = kwargs.user; const reason = kwargs.reason || 'Kein Grund'; return new EmbedBuilder().setTitle(`📋 Case #${kwargs.case_id}`).setDescription(`**${action}** gegen ${mention(user)}`).setColor(['BAN', 'KICK'].includes(action) ? COLORS.danger : COLORS.warning).addFields({ name: 'Grund', value: String(reason) }).setFooter({ text: 'Moderation System' }); }
function embed_case_updated(kwargs) { return new EmbedBuilder().setTitle(`✏️ Case #${kwargs.case_id} aktualisiert`).setDescription('Der Grund wurde geändert.').setColor(COLORS.info); }
function embed_automod_hit(kwargs) { return new EmbedBuilder().setTitle('🛡️ AutoMod').setDescription(`${mention(kwargs.user)} hat gegen eine Regel verstoßen.`).setColor(COLORS.warning).addFields({ name: 'Regel', value: String(kwargs.rule || 'Unbekannt') }).setFooter({ text: 'AutoMod' }); }
function embed_automod_blocked() { return new EmbedBuilder().setTitle('🚫 Nachricht blockiert').setDescription('Deine Nachricht wurde von AutoMod blockiert.').setColor(COLORS.danger); }
function embed_anti_spam(kwargs) { return new EmbedBuilder().setTitle('🚫 Anti-Spam').setDescription(`${mention(kwargs.user)} wurde wegen Spam eingeschränkt.`).setColor(COLORS.danger); }
function embed_anti_raid() { return new EmbedBuilder().setTitle('🚨 Anti-Raid erkannt').setDescription('Mögliche Raid-Aktivität wurde erkannt.').setColor(COLORS.danger); }
function embed_security_alert() { return new EmbedBuilder().setTitle('🚨 Security Alert').setDescription('Potentiell gefährliche Aktivität erkannt!').setColor(COLORS.danger).setFooter({ text: 'Security System' }); }
function embed_anti_nuke(kwargs) { return new EmbedBuilder().setTitle('🛡️ Anti-Nuke').setDescription(`${mention(kwargs.user)} hat versucht, den Server zu attackieren (${kwargs.action || 'unbekannt'}).`).setColor(COLORS.danger); }
function embed_whitelist_bypass(kwargs) { return new EmbedBuilder().setTitle('⚠️ Whitelist Bypass').setDescription(`${mention(kwargs.user)} hat versucht, eine geschützte Aktion auszuführen.`).setColor(COLORS.warning); }
function embed_backup_created() { return new EmbedBuilder().setTitle('💾 Backup erstellt').setDescription('Deine Server-Einstellungen wurden erfolgreich gesichert.').setColor(COLORS.success).setFooter({ text: 'Backup System' }); }
function embed_backup_restored(kwargs) { return new EmbedBuilder().setTitle('♻️ Backup wiederhergestellt').setDescription(`Backup **${kwargs.backup_id}** wurde erfolgreich wiederhergestellt.`).setColor(COLORS.info); }
function embed_log_message_delete(kwargs) { return new EmbedBuilder().setTitle('🗑️ Nachricht gelöscht').setDescription(`Von ${mention(kwargs.user)} in ${mention(kwargs.channel)}`).setColor(COLORS.dark).addFields({ name: 'Inhalt', value: String(kwargs.content || '').slice(0, 1024) || 'Kein Inhalt' }); }
function embed_log_message_edit(kwargs) { return new EmbedBuilder().setTitle('✏️ Nachricht bearbeitet').setDescription(`Von ${mention(kwargs.user)}`).setColor(COLORS.info); }
function embed_log_role_create(kwargs) { return new EmbedBuilder().setTitle('➕ Rolle erstellt').setDescription(`Rolle **${nameOf(kwargs.role)}** wurde erstellt.`).setColor(COLORS.success); }
function embed_log_role_delete(kwargs) { return new EmbedBuilder().setTitle('➖ Rolle gelöscht').setDescription(`Rolle **${kwargs.role_name}** wurde gelöscht.`).setColor(COLORS.danger); }
function embed_log_channel_create(kwargs) { return new EmbedBuilder().setTitle('➕ Kanal erstellt').setDescription(`Kanal **${nameOf(kwargs.channel)}** wurde erstellt.`).setColor(COLORS.success); }
function embed_log_member_join(kwargs) { return new EmbedBuilder().setTitle('➕ Member beigetreten').setDescription(`${mention(kwargs.user)} ist dem Server beigetreten.`).setColor(COLORS.success); }
function embed_log_member_leave(kwargs) { return new EmbedBuilder().setTitle('➖ Member verlassen').setDescription(`${kwargs.user} hat den Server verlassen.`).setColor(COLORS.dark); }
function embed_badge_added(kwargs) { return new EmbedBuilder().setTitle('🏅 Badge erhalten').setDescription(`${mention(kwargs.user)} hat das Badge **${kwargs.badge}** erhalten.`).setColor(COLORS.gold); }
function embed_badge_removed(kwargs) { return new EmbedBuilder().setTitle('🏅 Badge entfernt').setDescription(`Das Badge **${kwargs.badge}** wurde von ${mention(kwargs.user)} entfernt.`).setColor(COLORS.dark); }
function embed_leaderboard(kwargs) { return new EmbedBuilder().setTitle(`🏆 ${kwargs.title || 'Leaderboard'}`).setDescription('Hier sind die besten Mitglieder:').setColor(COLORS.gold); }
function embed_stats() { return new EmbedBuilder().setTitle('📊 Server Statistiken').setColor(COLORS.info).setFooter({ text: 'Stats System' }); }
function embed_success(kwargs) { return new EmbedBuilder().setTitle('✅ Erfolg').setDescription(kwargs.message || 'Erfolgreich!').setColor(COLORS.success); }
function embed_error(kwargs) { return new EmbedBuilder().setTitle('❌ Fehler').setDescription(kwargs.message || 'Ein Fehler ist aufgetreten.').setColor(COLORS.danger); }
function embed_info(kwargs) { return new EmbedBuilder().setTitle(kwargs.title || 'Information').setDescription(kwargs.description || '').setColor(COLORS.info); }
function embed_help(kwargs) { return new EmbedBuilder().setTitle(`❓ Hilfe: ${kwargs.command || 'Befehl'}`).setColor(COLORS.primary); }
function embed_pagination() { return new EmbedBuilder().setTitle('Seite').setColor(COLORS.dark); }
function embed_voice_join(kwargs) { return new EmbedBuilder().setTitle('🔊 Voice beigetreten').setDescription(`${mention(kwargs.user)} ist ${mention(kwargs.channel)} beigetreten.`).setColor(COLORS.teal); }
function embed_voice_leave(kwargs) { return new EmbedBuilder().setTitle('🔇 Voice verlassen').setDescription(`${mention(kwargs.user)} hat ${mention(kwargs.channel)} verlassen.`).setColor(COLORS.dark); }

const EMBEDS = {
  welcome: embed_welcome,
  leave: embed_leave,
  onboarding: embed_onboarding,
  verification_panel: embed_verification_panel,
  verification_success: embed_verification_success,
  verification_failed: embed_verification_failed,
  ticket_panel: embed_ticket_panel,
  ticket_created: embed_ticket_created,
  ticket_closed: embed_ticket_closed,
  ticket_transcript: embed_ticket_transcript,
  ticket_claimed: embed_ticket_claimed,
  tempvoice_panel: embed_tempvoice_panel,
  tempvoice_created: embed_tempvoice_created,
  tempvoice_deleted: embed_tempvoice_deleted,
  tempvoice_owner_action: embed_tempvoice_owner_action,
  ban: embed_ban,
  kick: embed_kick,
  mute: embed_mute,
  warn: embed_warn,
  case: embed_case,
  case_updated: embed_case_updated,
  automod_hit: embed_automod_hit,
  automod_blocked: embed_automod_blocked,
  anti_spam: embed_anti_spam,
  anti_raid: embed_anti_raid,
  security_alert: embed_security_alert,
  anti_nuke: embed_anti_nuke,
  whitelist_bypass: embed_whitelist_bypass,
  backup_created: embed_backup_created,
  backup_restored: embed_backup_restored,
  log_message_delete: embed_log_message_delete,
  log_message_edit: embed_log_message_edit,
  log_role_create: embed_log_role_create,
  log_role_delete: embed_log_role_delete,
  log_channel_create: embed_log_channel_create,
  log_member_join: embed_log_member_join,
  log_member_leave: embed_log_member_leave,
  badge_added: embed_badge_added,
  badge_removed: embed_badge_removed,
  leaderboard: embed_leaderboard,
  stats: embed_stats,
  success: embed_success,
  error: embed_error,
  info: embed_info,
  help: embed_help,
  pagination: embed_pagination,
  voice_join: embed_voice_join,
  voice_leave: embed_voice_leave,
};

module.exports = { getEmbed, get_embed: getEmbed, COLORS, EMBEDS };
