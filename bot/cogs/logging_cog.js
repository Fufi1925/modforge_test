const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { createEmbed } = require('../utils');
const { COLOR_SUCCESS, COLOR_PRIMARY, COLOR_DANGER, COLOR_WARNING, E, LOG_MODS } = require('../config');

const ALL_LOG_MODULES = Array.from(new Set([
  'default',
  ...LOG_MODS,
  'messages', 'message_delete', 'message_edit',
  'antishortener', 'voice', 'members', 'nicknames', 'channels', 'roles', 'webhooks',
  'warns', 'cases', 'backup', 'tempvoice', 'verification', 'automod', 'moderation',
  'antinuke', 'antiraid', 'antispam', 'antiscam', 'antimention', 'welcome', 'tickets'
])).sort();

function normalize(module) {
  const key = String(module || '').toLowerCase().trim().replace(/[-\s]+/g, '_');
  const aliases = {
    anti_spam: 'antispam', spam: 'antispam',
    anti_nuke: 'antinuke', nuke: 'antinuke',
    anti_raid: 'antiraid', raid: 'antiraid',
    anti_mention: 'antimention', mentions: 'antimention',
    anti_scam: 'antiscam', scam: 'antiscam',
    url_shortener: 'antishortener', anti_url_shortener: 'antishortener', urlshort: 'antishortener',
    verification: 'verify', ticket: 'tickets', temp_voice: 'tempvoice',
    voice_join: 'voice', voice_leave: 'voice', voice_switch: 'voice', voice_state: 'voice',
    member: 'members', member_join: 'members', member_leave: 'members',
    channel: 'channels', role: 'roles', webhook: 'webhooks',
    message: 'messages', message_delete: 'messages', message_edit: 'messages',
    mod: 'moderation'
  };
  return aliases[key] || key;
}

async function saveConfigAndSnapshot(bot, guildId, cfg) {
  cfg.log_channels = cfg.log_channels || {};
  await bot.db.setConfig(guildId, cfg);
  await bot.db.log_channels_snapshot(guildId, cfg.log_channels).catch(() => null);
}

async function setAllLogs(bot, guildId, channelId) {
  const cfg = await bot.db.fetchConfig(guildId);
  cfg.log_channel = channelId;
  cfg.log_channels = cfg.log_channels || {};
  for (const mod of ALL_LOG_MODULES) cfg.log_channels[mod] = channelId;
  await saveConfigAndSnapshot(bot, guildId, cfg);
  return cfg;
}

async function handleAllLogs(bot, interaction, channel) {
  await setAllLogs(bot, interaction.guild.id, channel.id);
  const embed = createEmbed(
    `${E.LOGS_CMD || '📝'} Logs eingerichtet`,
    `Alle **${ALL_LOG_MODULES.length} Log-Module** senden jetzt nach ${channel}.\n\n` +
    'Du kannst später einzelne Module mit `/logchannel` in eigene Kanäle verschieben.',
    COLOR_SUCCESS,
    [['Standard-Kanal', `${channel}`, true], ['Module', String(ALL_LOG_MODULES.length), true]],
  );
  await interaction.reply({ embeds: [embed], ephemeral: true });
  await channel.send({ embeds: [createEmbed(
    `${E.LOGS_CMD || '📝'} Log-Kanal aktiv`,
    `Dieser Kanal empfängt ab jetzt alle ModForge-Logs.\nKonfiguriert von ${interaction.user}.`,
    COLOR_SUCCESS,
  )] }).catch(() => null);
}

const commands = [
  {
    data: new SlashCommandBuilder().setName('log').setDescription('Setzt EINEN Kanal für ALLE Logs')
      .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
      .addChannelOption(o => o.setName('channel').setDescription('Kanal, in den alle Logs gesendet werden').setRequired(true)),
    async execute(bot, interaction) { await handleAllLogs(bot, interaction, interaction.options.getChannel('channel', true)); }
  },
  {
    data: new SlashCommandBuilder().setName('logs').setDescription('Alias: setzt EINEN Kanal für ALLE Logs')
      .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
      .addChannelOption(o => o.setName('channel').setDescription('Kanal, in den alle Logs gesendet werden').setRequired(true)),
    async execute(bot, interaction) { await handleAllLogs(bot, interaction, interaction.options.getChannel('channel', true)); }
  },
  {
    data: new SlashCommandBuilder().setName('logchannel').setDescription('Setzt den Log-Kanal für EIN bestimmtes Modul')
      .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
      .addStringOption(o => o.setName('module').setDescription('Log-Modul (z.B. moderation, antispam, channels)').setRequired(true))
      .addChannelOption(o => o.setName('channel').setDescription('Ziel-Kanal').setRequired(true)),
    async execute(bot, interaction) {
      const raw = interaction.options.getString('module', true);
      const moduleKey = normalize(raw);
      const channel = interaction.options.getChannel('channel', true);
      if (!ALL_LOG_MODULES.includes(moduleKey)) {
        return interaction.reply({ embeds: [createEmbed(`${E.FAIL} Unbekanntes Modul`, `\`${raw}\` ist kein gültiges Log-Modul. Nutze \`/logmodules\` für die Liste.`, COLOR_DANGER)], ephemeral: true });
      }
      const cfg = await bot.db.fetchConfig(interaction.guild.id);
      cfg.log_channels = cfg.log_channels || {};
      cfg.log_channels[moduleKey] = channel.id;
      await saveConfigAndSnapshot(bot, interaction.guild.id, cfg);
      await interaction.reply({ embeds: [createEmbed(`${E.OK} Modul-Log gesetzt`, `**${moduleKey}** sendet jetzt nach ${channel}.`, COLOR_SUCCESS)], ephemeral: true });
    }
  },
  {
    data: new SlashCommandBuilder().setName('logchannels').setDescription('Zeigt alle Log-Kanäle').setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
    async execute(bot, interaction) {
      const cfg = await bot.db.fetchConfig(interaction.guild.id);
      const logChannels = cfg.log_channels || {};
      const fallback = cfg.log_channel;
      const lines = [];
      if (fallback) lines.push(`**${E.CHANNEL} Standard:** <#${fallback}>`, '');
      if (Object.keys(logChannels).length) {
        const byChannel = new Map(); const disabled = [];
        for (const [mod, chId] of Object.entries(logChannels).sort()) {
          if (String(chId) === '0') disabled.push(mod);
          else if (chId) { const arr = byChannel.get(String(chId)) || []; arr.push(mod); byChannel.set(String(chId), arr); }
        }
        for (const [chId, mods] of byChannel) {
          const shown = mods.slice(0, 12).join(', ');
          const more = mods.length > 12 ? ` (+${mods.length - 12})` : '';
          lines.push(`<#${chId}>: ${shown}${more}`);
        }
        if (disabled.length) lines.push(`\n**Deaktiviert:** ${disabled.slice(0, 20).join(', ')}`);
      }
      if (!lines.length) lines.push('Keine Log-Kanäle konfiguriert. Nutze `/log #kanal`.');
      await interaction.reply({ embeds: [createEmbed(`${E.LOGS_CMD || '📝'} Log-Kanäle`, lines.join('\n').slice(0, 4000), COLOR_PRIMARY)], ephemeral: true });
    }
  },
  {
    data: new SlashCommandBuilder().setName('logchannel_remove').setDescription('Entfernt den Log-Kanal für ein Modul')
      .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
      .addStringOption(o => o.setName('module').setDescription('Log-Modul').setRequired(true)),
    async execute(bot, interaction) {
      const moduleKey = normalize(interaction.options.getString('module', true));
      const cfg = await bot.db.fetchConfig(interaction.guild.id);
      cfg.log_channels = cfg.log_channels || {};
      if (Object.prototype.hasOwnProperty.call(cfg.log_channels, moduleKey)) {
        delete cfg.log_channels[moduleKey];
        await saveConfigAndSnapshot(bot, interaction.guild.id, cfg);
        await interaction.reply({ embeds: [createEmbed(`${E.OK} Modul zurückgesetzt`, `**${moduleKey}** nutzt wieder den Standard-Log-Kanal.`, COLOR_SUCCESS)], ephemeral: true });
      } else {
        await interaction.reply({ embeds: [createEmbed(`${E.FAIL} Nicht gesetzt`, `Für **${moduleKey}** war kein eigener Kanal gesetzt.`, COLOR_DANGER)], ephemeral: true });
      }
    }
  },
  {
    data: new SlashCommandBuilder().setName('log_test').setDescription('Sendet Test-Logs in alle konfigurierten Log-Kanäle').setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
    async execute(bot, interaction) {
      const cfg = await bot.db.fetchConfig(interaction.guild.id);
      const targets = {};
      if (cfg.log_channel) targets.default = cfg.log_channel;
      for (const [module, channelId] of Object.entries(cfg.log_channels || {})) if (channelId && String(channelId) !== '0') targets[module] = channelId;
      if (!Object.keys(targets).length) return interaction.reply({ embeds: [createEmbed(`${E.FAIL} Keine Logs eingerichtet`, 'Nutze zuerst `/log #kanal`.', COLOR_DANGER)], ephemeral: true });
      await interaction.deferReply({ ephemeral: true });
      let ok = 0; const failed = [];
      for (const [module, channelId] of Object.entries(targets).sort()) {
        const ch = await interaction.guild.channels.fetch(channelId).catch(() => null);
        if (!ch?.isTextBased?.()) { failed.push(`${module}: Kanal nicht gefunden`); continue; }
        try { await ch.send({ embeds: [createEmbed(`${E.LOGS_CMD || '📝'} Test-Log · ${module}`, `Dieser Test wurde von ${interaction.user} ausgelöst. Modul **${module}** funktioniert.`, COLOR_SUCCESS)] }); ok += 1; }
        catch (error) { failed.push(`${module}: ${error.message}`); }
      }
      await interaction.followUp({ embeds: [createEmbed(`${E.LOGS_CMD || '📝'} Log-Test fertig`, `✅ Erfolgreich: **${ok}**\n❌ Fehler: **${failed.length}**`, failed.length ? COLOR_WARNING : COLOR_SUCCESS, [['Fehler', failed.slice(0, 10).join('\n') || 'Keine', false]])], ephemeral: true });
    }
  },
  {
    data: new SlashCommandBuilder().setName('logmodules').setDescription('Zeigt alle verfügbaren Log-Module').setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
    async execute(bot, interaction) {
      const chunks = []; let current = [];
      for (const module of ALL_LOG_MODULES) { current.push(`\`${module}\``); if (current.join(', ').length > 900) { chunks.push(current.join(', ')); current = []; } }
      if (current.length) chunks.push(current.join(', '));
      await interaction.reply({ embeds: [createEmbed(`${E.LOGS_CMD || '📝'} Log-Module (${ALL_LOG_MODULES.length})`, 'Nutze `/logchannel <modul> #kanal` für einzelne Module oder `/log #kanal` für alles.', COLOR_PRIMARY, chunks.slice(0, 4).map((chunk, i) => [`Module ${i + 1}`, chunk, false]))], ephemeral: true });
    }
  },
  {
    data: new SlashCommandBuilder().setName('logs_disable').setDescription('Deaktiviert alle Logs').setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
    async execute(bot, interaction) {
      const cfg = await bot.db.fetchConfig(interaction.guild.id);
      cfg.log_channel = null; cfg.log_channels = {};
      await saveConfigAndSnapshot(bot, interaction.guild.id, cfg);
      await interaction.reply({ embeds: [createEmbed(`${E.OK} Logs deaktiviert`, 'Alle Log-Kanäle wurden entfernt. Aktiviere sie wieder mit `/log #kanal`.', COLOR_WARNING)], ephemeral: true });
    }
  },
];
module.exports = { commands, ALL_LOG_MODULES, normalize };
