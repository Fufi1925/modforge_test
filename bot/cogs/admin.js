const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { createEmbed } = require('../utils');
const { COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER, COLOR_INFO, E } = require('../config');

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function respond(interaction, payload, ephemeral = false) { if (interaction.deferred || interaction.replied) return interaction.followUp({ ...payload, ephemeral }); return interaction.reply({ ...payload, ephemeral }); }

const commands = [
  {
    data: new SlashCommandBuilder().setName('case').setDescription('Zeigt einen Case an')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages)
      .addIntegerOption(o => o.setName('case_id').setDescription('Case-ID').setRequired(true)),
    async execute(bot, interaction) {
      const caseId = interaction.options.getInteger('case_id', true);
      const c = await bot.db.aget_case(interaction.guild.id, caseId);
      if (!c) return interaction.reply({ embeds: [createEmbed(`${E.FAIL}`, `Case #${caseId} nicht gefunden.`, COLOR_DANGER)], ephemeral: true });
      const fields = [
        ['Aktion', c.action || '?', true],
        ['User', `<@${c.user_id || 0}>`, true],
        ['Moderator', `<@${c.mod_id || c.moderator_id || 0}>`, true],
        ['Grund', c.reason || '—', false],
      ];
      if (c.duration) fields.push(['Dauer', `${c.duration}s`, true]);
      if (c.evidence) fields.push(['Beweise', String(c.evidence.length), true]);
      if (c.message_archive) fields.push(['Archivierte Nachrichten', String(c.message_archive.length), true]);
      await interaction.reply({ embeds: [createEmbed(`${E.CASE} Case #${caseId}`, '', COLOR_PRIMARY, fields)] });
    }
  },
  {
    data: new SlashCommandBuilder().setName('cases').setDescription('Zeigt die letzten Cases')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages)
      .addIntegerOption(o => o.setName('limit').setDescription('Anzahl (max 50)').setRequired(false)),
    async execute(bot, interaction) {
      const limit = Math.min(interaction.options.getInteger('limit') || 20, 50);
      const cases = await bot.db.aget_recent_cases(interaction.guild.id, limit);
      if (!cases.length) return interaction.reply({ embeds: [createEmbed(`${E.OK}`, 'Keine Cases vorhanden.', COLOR_INFO)] });
      const lines = [];
      for (const c of cases) {
        const actionEmoji = { ban: E.BAN, kick: E.KICK, warn: E.WARN, timeout: E.MUTE, mute: E.MUTE, softban: E.BAN, tempban: E.TIMER, tempmute: E.TIMER }[c.action || ''] || E.CASE;
        lines.push(`${actionEmoji} \`#${c.case_id || '?'}\` ${c.action || '?'} – <@${c.user_id || 0}> – ${String(c.reason || '—').slice(0, 30)}`);
      }
      await interaction.reply({ embeds: [createEmbed(`${E.CASE} Cases (${cases.length})`, lines.slice(0, 25).join('\n'), COLOR_PRIMARY)] });
    }
  },
  {
    data: new SlashCommandBuilder().setName('case_edit').setDescription('Ändert den Grund eines Cases')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages)
      .addIntegerOption(o => o.setName('case_id').setDescription('Case-ID').setRequired(true))
      .addStringOption(o => o.setName('reason').setDescription('Neuer Grund').setRequired(true)),
    async execute(bot, interaction) {
      const caseId = interaction.options.getInteger('case_id', true);
      const reason = interaction.options.getString('reason', true);
      const ok = await bot.db.aupdate_case_reason(interaction.guild.id, caseId, reason, interaction.user.id);
      if (ok) await interaction.reply({ embeds: [createEmbed(`${E.OK} Case #${caseId} aktualisiert`, `Neuer Grund: ${reason}`, COLOR_SUCCESS)] });
      else await interaction.reply({ embeds: [createEmbed(`${E.FAIL}`, 'Case nicht gefunden.', COLOR_DANGER)], ephemeral: true });
    }
  },
  {
    data: new SlashCommandBuilder().setName('audit-perms').setDescription('Prüft gefährliche Berechtigungen').setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
    async execute(bot, interaction) {
      const cfg = await bot.db.fetchConfig(interaction.guild.id);
      const dangerPerms = cfg.perms_audit?.danger_perms || ['administrator', 'manage_guild', 'manage_roles', 'manage_channels', 'ban_members', 'kick_members', 'manage_webhooks'];
      const map = { administrator: PermissionFlagsBits.Administrator, manage_guild: PermissionFlagsBits.ManageGuild, manage_roles: PermissionFlagsBits.ManageRoles, manage_channels: PermissionFlagsBits.ManageChannels, ban_members: PermissionFlagsBits.BanMembers, kick_members: PermissionFlagsBits.KickMembers, manage_webhooks: PermissionFlagsBits.ManageWebhooks, manage_messages: PermissionFlagsBits.ManageMessages, mention_everyone: PermissionFlagsBits.MentionEveryone, moderate_members: PermissionFlagsBits.ModerateMembers };
      const issues = [];
      for (const role of interaction.guild.roles.cache.values()) {
        if (role.id === interaction.guild.id || role.managed) continue;
        for (const permName of dangerPerms) if (map[permName] && role.permissions.has(map[permName])) issues.push(`${permName === 'administrator' ? `${E.FAIL} CRITICAL` : `${E.WARN} HIGH`} ${role} → \`${permName}\``);
      }
      if (!issues.length) return interaction.reply({ embeds: [createEmbed(`${E.OK} Keine Probleme`, 'Alle Berechtigungen sehen sicher aus.', COLOR_SUCCESS)] });
      let desc = issues.slice(0, 30).join('\n'); if (issues.length > 30) desc += `\n\n... und ${issues.length - 30} weitere`;
      await interaction.reply({ embeds: [createEmbed(`${E.SHIELD} Berechtigungs-Audit (${issues.length} Funde)`, desc, COLOR_WARNING)] });
    }
  },
  {
    data: new SlashCommandBuilder().setName('massunban').setDescription('Entbannt ALLE gebannten User').setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
    async execute(bot, interaction) {
      await interaction.deferReply();
      let unbanned = 0;
      try {
        const bans = await interaction.guild.bans.fetch();
        for (const entry of bans.values()) { if (await interaction.guild.members.unban(entry.user, 'Mass-Unban').then(() => true).catch(() => false)) unbanned++; if (unbanned % 10 === 0) await sleep(1000); }
      } catch { return interaction.followUp({ embeds: [createEmbed(`${E.FAIL}`, 'Keine Berechtigung für Banliste.', COLOR_DANGER)] }); }
      await interaction.followUp({ embeds: [createEmbed(`${E.OK} Mass-Unban`, `${unbanned} User entbannt.`, COLOR_SUCCESS)] });
    }
  },
  {
    data: new SlashCommandBuilder().setName('massban').setDescription('Bannt mehrere Nutzer gleichzeitig')
      .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers)
      .addStringOption(o => o.setName('user_ids').setDescription('User-IDs (kommagetrennt)').setRequired(true))
      .addStringOption(o => o.setName('reason').setDescription('Grund').setRequired(false)),
    async execute(bot, interaction) {
      await interaction.deferReply();
      const reason = interaction.options.getString('reason') || 'Mass-Ban';
      const ids = interaction.options.getString('user_ids', true).split(',').map(s => s.trim()).filter(s => /^\d+$/.test(s));
      let banned = 0;
      for (const uid of ids) { if (await interaction.guild.members.ban(uid, { reason }).then(() => true).catch(() => false)) banned++; await sleep(500); }
      await interaction.followUp({ embeds: [createEmbed(`${E.OK} Mass-Ban`, `${banned}/${ids.length} User gebannt.\nGrund: ${reason}`, COLOR_SUCCESS)] });
    }
  },
  {
    data: new SlashCommandBuilder().setName('massrole_remove').setDescription('Entfernt eine Rolle von allen Mitgliedern')
      .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
      .addRoleOption(o => o.setName('role').setDescription('Die Rolle').setRequired(true)),
    async execute(bot, interaction) {
      await interaction.deferReply(); const role = interaction.options.getRole('role', true); let removed = 0;
      await interaction.guild.members.fetch().catch(() => null);
      for (const member of role.members.values()) { if (await member.roles.remove(role, 'Mass-Role Remove').then(() => true).catch(() => false)) removed++; if (removed % 5 === 0) await sleep(1000); }
      await interaction.followUp({ embeds: [createEmbed(`${E.OK} Mass-Role Remove`, `${role} von ${removed} Mitgliedern entfernt.`, COLOR_SUCCESS)] });
    }
  },
  {
    data: new SlashCommandBuilder().setName('setarchive').setDescription('Setzt den Archiv-Kanal').setDefaultMemberPermissions(PermissionFlagsBits.Administrator).addChannelOption(o => o.setName('channel').setDescription('Der Kanal').setRequired(true)),
    async execute(bot, interaction) { const ch = interaction.options.getChannel('channel', true); const cfg = await bot.db.fetchConfig(interaction.guild.id); cfg.archive_channel = ch.id; await bot.db.setConfig(interaction.guild.id, cfg); await interaction.reply({ embeds: [createEmbed(`${E.OK} Archiv-Kanal`, `Gesetzt auf ${ch}`, COLOR_SUCCESS)] }); }
  },
  {
    data: new SlashCommandBuilder().setName('banappeal').setDescription('Ban-Appeal System konfigurieren').setDefaultMemberPermissions(PermissionFlagsBits.Administrator).addBooleanOption(o => o.setName('enabled').setDescription('Aktivieren/Deaktivieren').setRequired(true)),
    async execute(bot, interaction) { const enabled = interaction.options.getBoolean('enabled', true); const cfg = await bot.db.fetchConfig(interaction.guild.id); cfg.auto_ban_appeal = { enabled }; await bot.db.setConfig(interaction.guild.id, cfg); await interaction.reply({ embeds: [createEmbed(`${E.OK} Ban-Appeal`, `System **${enabled ? 'aktiviert' : 'deaktiviert'}**.`, COLOR_SUCCESS)] }); }
  },
  {
    data: new SlashCommandBuilder().setName('appeal_channel').setDescription('Setzt den Appeal-Log-Kanal').setDefaultMemberPermissions(PermissionFlagsBits.Administrator).addChannelOption(o => o.setName('channel').setDescription('Der Kanal').setRequired(true)),
    async execute(bot, interaction) { const ch = interaction.options.getChannel('channel', true); const cfg = await bot.db.fetchConfig(interaction.guild.id); cfg.appeal_log_channel = ch.id; await bot.db.setConfig(interaction.guild.id, cfg); await interaction.reply({ embeds: [createEmbed(`${E.OK} Appeal-Kanal`, `Gesetzt auf ${ch}`, COLOR_SUCCESS)] }); }
  },
  {
    data: new SlashCommandBuilder().setName('invites').setDescription('Invite-Statistiken eines Users').addUserOption(o => o.setName('member').setDescription('Der Nutzer').setRequired(false)),
    async execute(bot, interaction) { const member = interaction.options.getMember('member') || interaction.member; const invites = await interaction.guild.invites.fetch().catch(() => null); if (!invites) return interaction.reply({ embeds: [createEmbed(`${E.FAIL}`, 'Ich kann die Invites nicht lesen.', COLOR_DANGER)], ephemeral: true }); const uses = invites.filter(inv => inv.inviter?.id === member.id).reduce((a, inv) => a + (inv.uses || 0), 0); await interaction.reply({ embeds: [createEmbed(`${E.APPEAL} Invites`, `${member} hat **${uses}** Invites.`, COLOR_PRIMARY)] }); }
  },
  {
    data: new SlashCommandBuilder().setName('modstats').setDescription('Moderator-Statistiken').setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages).addUserOption(o => o.setName('moderator').setDescription('Der Moderator').setRequired(false)),
    async execute(bot, interaction) { const mod = interaction.options.getUser('moderator') || interaction.user; const cases = await bot.db.aget_recent_cases(interaction.guild.id, 200); const own = cases.filter(c => String(c.mod_id || c.moderator_id) === String(mod.id)); await interaction.reply({ embeds: [createEmbed(`${E.STATS} Moderator-Statistiken`, `${mod} hat **${own.length}** Cases.`, COLOR_PRIMARY)] }); }
  },
  {
    data: new SlashCommandBuilder().setName('report').setDescription('Meldet einen User').addUserOption(o => o.setName('member').setDescription('Der Nutzer').setRequired(true)).addStringOption(o => o.setName('reason').setDescription('Grund').setRequired(true)),
    async execute(bot, interaction) { const member = interaction.options.getMember('member'); const reason = interaction.options.getString('reason', true); const cfg = await bot.db.fetchConfig(interaction.guild.id); const ch = cfg.report_channel ? await interaction.guild.channels.fetch(cfg.report_channel).catch(() => null) : null; if (!ch) return interaction.reply({ embeds: [createEmbed(`${E.FAIL}`, 'Kein Report-Kanal gesetzt.', COLOR_DANGER)], ephemeral: true }); await ch.send({ embeds: [createEmbed(`${E.REPORT} Report`, `**Gemeldet:** ${member}\n**Von:** ${interaction.user}\n**Grund:** ${reason}`, COLOR_WARNING)] }); await interaction.reply({ embeds: [createEmbed(`${E.OK}`, 'Report gesendet.', COLOR_SUCCESS)], ephemeral: true }); }
  },
  {
    data: new SlashCommandBuilder().setName('report_setup').setDescription('Setzt den Report-Kanal').setDefaultMemberPermissions(PermissionFlagsBits.Administrator).addChannelOption(o => o.setName('channel').setDescription('Der Kanal').setRequired(true)),
    async execute(bot, interaction) { const ch = interaction.options.getChannel('channel', true); const cfg = await bot.db.fetchConfig(interaction.guild.id); cfg.report_channel = ch.id; await bot.db.setConfig(interaction.guild.id, cfg); await interaction.reply({ embeds: [createEmbed(`${E.OK} Report-Kanal`, `Gesetzt auf ${ch}`, COLOR_SUCCESS)] }); }
  },
  {
    data: new SlashCommandBuilder().setName('backup_autosetup').setDescription('Auto-Backup konfigurieren').setDefaultMemberPermissions(PermissionFlagsBits.Administrator).addBooleanOption(o => o.setName('enabled').setDescription('Aktivieren/Deaktivieren').setRequired(true)).addIntegerOption(o => o.setName('interval_hours').setDescription('Intervall in Stunden').setRequired(false)),
    async execute(bot, interaction) { const enabled = interaction.options.getBoolean('enabled', true); const interval = interaction.options.getInteger('interval_hours') || 24; const cfg = await bot.db.fetchConfig(interaction.guild.id); cfg.backup_system = cfg.backup_system || {}; cfg.backup_system.auto_enabled = enabled; cfg.backup_system.auto_interval_hours = interval; await bot.db.setConfig(interaction.guild.id, cfg); await interaction.reply({ embeds: [createEmbed(`${E.OK} Auto-Backup`, `Auto-Backup **${enabled ? 'aktiviert' : 'deaktiviert'}**. Intervall: **${interval}h**`, COLOR_SUCCESS)] }); }
  },
];
module.exports = { commands };
