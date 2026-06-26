// -*- coding: utf-8 -*-
// ModForge – Discord Bot Core (Node.js Migration)
const fs = require('node:fs');
const path = require('node:path');
const {
  Client,
  Collection,
  GatewayIntentBits,
  Partials,
  ActivityType,
  PermissionFlagsBits,
  Events,
} = require('discord.js');

const { Database } = require('../database/db');
const { ACTIVITY, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER, devPrint, devBanner, getUptime } = require('./config');
const { createEmbed, runWithEmbedContext, modernizeEmbed, embedPayload, createButtonRows, defaultEmbedButtons } = require('./utils');

class Tracker {
  constructor() {
    this.spamTracker = new Map();
    this.dupTracker = new Map();
    this.nukeTracker = new Map();
    this.raidTracker = new Map();
    this.newAccountTracker = new Map();
    this.mentionTracker = new Map();
    this.webhookTracker = new Map();
    this.ghostTracker = new Map();
    this.lockdownActive = new Map();
    this.inviteCache = new Map();
  }
  cleanOld(list, windowSeconds) {
    const now = Date.now();
    while (list.length && now - list[0] > windowSeconds * 1000) list.shift();
  }
}

class ModForge extends Client {
  constructor() {
    super({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMembers,
        GatewayIntentBits.GuildModeration,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.GuildMessageReactions,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages,
      ],
      partials: [Partials.Channel, Partials.Message, Partials.Reaction, Partials.User, Partials.GuildMember],
    });
    this.db = new Database();
    this.tracker = new Tracker();
    this.commands = new Collection();
    this.prefixCommands = new Collection();
    this.startTime = Date.now();
    this.statusRotation = [
      { type: ActivityType.Watching, name: '🔒 ModForge Security | /help', duration: 10000 },
      { type: ActivityType.Streaming, name: '🛡️ Anti Raid Active | /help', duration: 3000 },
      { type: ActivityType.Listening, name: '🎵 Security Reports | /logs', duration: 3000 },
      { type: ActivityType.Playing, name: '🔥 Live Protection | /setup', duration: 3000 },
      { type: ActivityType.Competing, name: '👀 Watching {member_count} Members | /help', duration: 10000 },
    ];
  }

  async start(token) {
    await this.db.testConnection();
    await this.loadCogs();
    this.registerCoreEvents();
    return this.login(token);
  }

  async loadCogs() {
    const cogsDir = path.join(__dirname, 'cogs');
    const files = fs.readdirSync(cogsDir).filter((file) => file.endsWith('.js') && file !== '__init__.js');
    for (const file of files) {
      try {
        const cog = require(path.join(cogsDir, file));
        if (typeof cog.setup === 'function') await cog.setup(this);
        for (const command of cog.commands || []) this.addSlashCommand(command, file);
        for (const command of cog.prefixCommands || []) this.addPrefixCommand(command, file);
        for (const event of cog.events || []) this.addEvent(event, file);
        devPrint(`Cog geladen: bot/cogs/${file}`, 'success', 'Cogs');
      } catch (error) {
        devPrint(`Cog konnte nicht geladen werden: bot/cogs/${file} → ${error.message}`, 'error', 'Cogs');
      }
    }
  }

  addSlashCommand(command, file = 'unknown') {
    const name = command?.data?.name || command?.name;
    if (!name) return;
    if (this.commands.has(name)) {
      devPrint(`Slash-Command doppelt übersprungen: /${name} (${file})`, 'warning', 'Commands');
      return;
    }
    this.commands.set(name, command);
  }

  addPrefixCommand(command, file = 'unknown') {
    const names = [command.name, ...(command.aliases || [])].filter(Boolean);
    for (const name of names) this.prefixCommands.set(name, command);
  }

  addEvent(event, file = 'unknown') {
    if (!event || !event.name || typeof event.execute !== 'function') return;
    const handler = (...args) => event.execute(this, ...args).catch((error) => devPrint(`Event ${event.name} (${file}) Fehler: ${error.message}`, 'error', 'Events'));
    if (event.once) this.once(event.name, handler);
    else this.on(event.name, handler);
  }

  modernizeInteractionPayload(payload, interaction) {
    if (!payload || typeof payload === 'string') return payload;
    const body = { ...payload };
    if (Array.isArray(body.embeds)) {
      body.embeds = body.embeds.map((embed) => modernizeEmbed(embed, { author: interaction.user, guild: interaction.guild }));
      if (!body.components) {
        const rows = createButtonRows(defaultEmbedButtons({ guild: interaction.guild }));
        if (rows.length) body.components = rows;
      }
    }
    return body;
  }

  patchInteractionEmbeds(interaction) {
    if (interaction.__modforgeEmbedPatched) return;
    interaction.__modforgeEmbedPatched = true;
    for (const method of ['reply', 'followUp', 'editReply']) {
      if (typeof interaction[method] !== 'function') continue;
      const original = interaction[method].bind(interaction);
      interaction[method] = (payload, ...rest) => original(this.modernizeInteractionPayload(payload, interaction), ...rest);
    }
  }

  registerCoreEvents() {
    this.once(Events.ClientReady, async () => {
      const totalMembers = this.guilds.cache.reduce((sum, guild) => sum + (guild.memberCount || 0), 0);
      devBanner('ModForge ist online', `Bot: ${this.user.tag} (${this.user.id})`, `Server: ${this.guilds.cache.size}`, `Member: ${totalMembers.toLocaleString('de-DE')}`, 'success', 'Ready');
      ACTIVITY.push('ready', `Bot online als ${this.user.tag} – ${this.guilds.cache.size} Guilds, ${totalMembers} Member.`);
      await this.warmupCaches();
      await this.syncSlashCommands();
      this.rotateStatus();
    });

    this.on('interactionCreate', async (interaction) => {
      if (!interaction.isChatInputCommand()) return;
      const command = this.commands.get(interaction.commandName);
      if (!command) return;
      this.patchInteractionEmbeds(interaction);
      try {
        await runWithEmbedContext({ interaction, user: interaction.user, author: interaction.user }, () => command.execute(this, interaction));
      } catch (error) {
        devPrint(`Command /${interaction.commandName} Fehler: ${error.stack || error.message}`, 'error', 'Commands');
        const embed = createEmbed('❌ Fehler', 'Beim Ausführen des Commands ist ein Fehler aufgetreten.', COLOR_DANGER, [], { author: interaction.user });
        if (interaction.deferred || interaction.replied) await interaction.editReply({ embeds: [modernizeEmbed(embed, { author: interaction.user })] }).catch(() => null);
        else await interaction.reply({ embeds: [modernizeEmbed(embed, { author: interaction.user })], ephemeral: true }).catch(() => null);
      }
    });

    this.on('messageCreate', async (message) => {
      if (!message.guild || message.author.bot) return;
      const cfg = await this.db.fetchConfig(message.guild.id).catch(() => this.db.getConfig(message.guild.id));
      const prefix = cfg.prefix || '!';
      if (!message.content.startsWith(prefix)) return;
      const [name, ...args] = message.content.slice(prefix.length).trim().split(/\s+/);
      const command = this.prefixCommands.get(String(name || '').toLowerCase());
      if (!command) return;
      try {
        await command.execute(this, message, args);
      } catch (error) {
        devPrint(`Prefix-Command ${name} Fehler: ${error.message}`, 'error', 'Commands');
      }
    });
  }

  async warmupCaches() {
    let ok = 0;
    let failed = 0;
    for (const guild of this.guilds.cache.values()) {
      try {
        const cfg = await this.db.fetchConfig(guild.id);
        await this.db.fetchWhitelist(guild.id).catch(() => null);
        const backup = await this.db.log_channels_restore(guild.id).catch(() => null);
        if (backup && Object.keys(backup).length && (!cfg.log_channels || !Object.keys(cfg.log_channels).length)) {
          cfg.log_channels = backup;
          await this.db.setConfig(guild.id, cfg);
        }
        ok += 1;
      } catch (error) {
        failed += 1;
        devPrint(`Cache-Warmup fehlgeschlagen für ${guild.name}: ${error.message}`, 'warning', 'Cache');
      }
    }
    devPrint(`Cache-Warmup fertig: ${ok} OK, ${failed} fehlgeschlagen`, failed ? 'warning' : 'success', 'Cache');
  }

  async syncSlashCommands() {
    try {
      const payload = [...this.commands.values()].map((cmd) => cmd.data.toJSON ? cmd.data.toJSON() : cmd.data);
      await this.application.commands.set(payload);
      devPrint('Slash-Commands erfolgreich synchronisiert.', 'success', 'Commands');
    } catch (error) {
      devPrint(`Slash-Command Sync fehlgeschlagen: ${error.message}`, 'error', 'Commands');
    }
  }

  rotateStatus() {
    let index = 0;
    const tick = () => {
      const item = this.statusRotation[index % this.statusRotation.length];
      const totalMembers = this.guilds.cache.reduce((sum, guild) => sum + (guild.memberCount || 0), 0);
      const name = item.name.replace('{member_count}', totalMembers.toLocaleString('de-DE'));
      try {
        this.user.setActivity(name, { type: item.type });
      } catch (error) {
        devPrint(`Status-Rotation Fehler: ${error.message}`, 'debug', 'Presence');
      }
      index += 1;
      setTimeout(tick, item.duration);
    };
    tick();
  }

  async createCase(guild, action, target, moderator, reason = 'Kein Grund') {
    const doc = await this.db.createCase(guild.id, {
      action,
      user_id: target?.id ? String(target.id) : null,
      user_tag: target?.tag || target?.user?.tag || String(target || 'Unbekannt'),
      moderator_id: moderator?.id ? String(moderator.id) : null,
      moderator_tag: moderator?.tag || moderator?.user?.tag || String(moderator || 'System'),
      reason,
    });
    return doc;
  }

  async createModCase(guild, target, moderator, action, reason, duration = null) {
    const targetId = target?.id || target;
    const doc = await this.db.acreate_case(guild.id, targetId, moderator?.id || moderator, action, reason, duration);
    ACTIVITY.push('case', `Case #${doc.case_id} (${action}) – Target \`${targetId}\` von ${moderator}.`, { guild_id: guild.id, guild_name: guild.name, user_id: moderator?.id, user_name: String(moderator) });
    return doc.case_id;
  }

  isWhitelisted(member, bypassType = null) {
    if (!member || !member.guild) return false;
    if (this.user && member.id === this.user.id) return true;
    if (member.id === member.guild.ownerId) return true;
    const wl = this.db.getWhitelist(member.guild.id);
    if (String(member.id) === '1303627964734246944') return true;
    const users = (wl.users || []).map(String);
    const roles = (wl.roles || []).map(String);
    if (users.includes(String(member.id))) return true;
    if (member.roles?.cache?.some((role) => roles.includes(String(role.id)))) return true;
    if (bypassType && (wl[bypassType] || []).map(String).includes(String(member.id))) return true;
    return false;
  }

  is_whitelisted(member, bypassType = null) { return this.isWhitelisted(member, bypassType); }

  async punish(member, punishment, reason, duration = 60, moderatorId = null, deleteMessageSeconds = null) {
    const guild = member.guild;
    const modId = moderatorId || this.user.id;
    let executed = false;
    let caseId = null;
    try {
      if (punishment === 'warn') {
        const cfg = await this.db.fetchConfig(guild.id);
        cfg.warns = cfg.warns || {};
        cfg.warns[String(member.id)] = cfg.warns[String(member.id)] || [];
        cfg.warns[String(member.id)].push({ reason, time: new Date().toISOString(), mod: modId });
        await this.db.setConfig(guild.id, cfg);
        executed = true;
      } else if (punishment === 'timeout') {
        duration = Math.max(1, Math.min(Number(duration || 60), 60 * 60 * 24 * 28));
        await member.timeout(duration * 1000, reason);
        await member.send(embedPayload(createEmbed('🔇 Du wurdest getimeoutet', `**Server:** ${guild.name}\n**Von:** ${this.user.tag}\n**Dauer:** ${duration} Sekunden\n**Grund:** ${reason}`, COLOR_WARNING, [], { author: this.user, guild }), { author: this.user, guild })).catch(() => null);
        executed = true;
      } else if (punishment === 'kick') {
        await member.send(embedPayload(createEmbed('👢 Du wurdest gekickt', `**Server:** ${guild.name}\n**Grund:** ${reason}`, COLOR_WARNING, [], { author: this.user, guild }), { author: this.user, guild })).catch(() => null);
        await member.kick(reason);
        executed = true;
      } else if (punishment === 'ban') {
        await member.send(embedPayload(createEmbed('🔨 Du wurdest gebannt', `**Server:** ${guild.name}\n**Grund:** ${reason}`, COLOR_DANGER, [], { author: this.user, guild }), { author: this.user, guild })).catch(() => null);
        const deleteMessageSecondsSafe = deleteMessageSeconds == null ? 86400 : Math.max(0, Math.min(Number(deleteMessageSeconds), 604800));
        await member.ban({ reason, deleteMessageSeconds: deleteMessageSecondsSafe });
        executed = true;
        const doc = await this.db.acreate_case(guild.id, member.id, modId, 'ban', reason);
        caseId = doc.case_id;
        ACTIVITY.push('case', `Case #${caseId} (ban) – ${member}`, { guild_id: guild.id, guild_name: guild.name, user_id: member.id, user_name: String(member) });
        await this.logAction(guild, `🛡️ Case #${caseId} – Ban`, `**User:** ${member} (\`${member.id}\`)\n**Grund:** ${reason}\n**Archiv:** 0 Nachrichten`, COLOR_DANGER, { user: member, module: 'cases' });
        return caseId;
      }
    } catch (e) {
      devPrint(`Fehler bei Strafe '${punishment}': ${e.message}`, 'warning', 'Moderation');
    }
    if (executed && ['warn', 'timeout', 'kick'].includes(punishment)) {
      const doc = await this.db.acreate_case(guild.id, member.id, modId, punishment, reason, punishment === 'timeout' ? duration : null);
      caseId = doc.case_id;
      ACTIVITY.push('case', `Case #${caseId} (${punishment}) – ${member}`, { guild_id: guild.id, guild_name: guild.name, user_id: member.id, user_name: String(member) });
      return caseId;
    }
    return null;
  }

  normalizeLogModule(module) {
    const key = String(module || 'default').toLowerCase().trim().replace(/[-\s]+/g, '_');
    const aliases = {
      antispam: 'antispam', anti_spam: 'antispam', spam: 'antispam',
      antinuke: 'antinuke', anti_nuke: 'antinuke', nuke: 'antinuke',
      antiraid: 'antiraid', anti_raid: 'antiraid', raid: 'antiraid',
      antimention: 'antimention', anti_mention: 'antimention', mentions: 'antimention',
      antiscam: 'antiscam', anti_scam: 'antiscam', scam: 'antiscam',
      urlshort: 'antishortener', url_shortener: 'antishortener', antishortener: 'antishortener', anti_url_shortener: 'antishortener',
      verify: 'verify', verification: 'verify',
      ticket: 'tickets', tickets: 'tickets',
      temp_voice: 'tempvoice', tempvoice: 'tempvoice',
      voice_join: 'voice', voice_leave: 'voice', voice_switch: 'voice', voice_state: 'voice', voice: 'voice',
      member: 'members', members: 'members', member_join: 'members', member_leave: 'members',
      channel: 'channels', channels: 'channels',
      role: 'roles', roles: 'roles',
      webhook: 'webhooks', webhooks: 'webhooks',
      message: 'messages', messages: 'messages', message_delete: 'messages', message_edit: 'messages',
      moderation: 'moderation', mod: 'moderation', warns: 'warns', cases: 'cases', backup: 'backup', welcome: 'welcome', default: 'default'
    };
    return aliases[key] || key;
  }

  resolveLogChannelId(cfg, module, explicit = null) {
    if (explicit) return explicit;
    const channels = cfg.log_channels || {};
    const moduleKey = this.normalizeLogModule(module);
    const candidates = [module, moduleKey, String(module || '').replace(/_/g, ''), 'default'];
    for (const raw of candidates) {
      if (!raw) continue;
      const key = String(raw).toLowerCase();
      if (Object.prototype.hasOwnProperty.call(channels, key)) {
        const value = channels[key];
        if (String(value) === '0') return null;
        if (value) return value;
      }
    }
    if (cfg.log_channel && String(cfg.log_channel) !== '0') return cfg.log_channel;
    return null;
  }

  async logAction(guild, title, description, color = COLOR_PRIMARY, options = {}) {
    try {
      if (!guild) return false;
      const cfg = await this.db.fetchConfig(guild.id);
      const moduleKey = this.normalizeLogModule(options.module || 'default');
      const channelId = this.resolveLogChannelId(cfg, moduleKey, options.channelId);
      if (!channelId) return false;
      const channel = await guild.channels.fetch(channelId).catch(() => null);
      if (!channel || !channel.isTextBased()) return false;
      const author = options.author || options.executor || options.mod || options.actor || options.user || this.user;
      const embed = createEmbed(title, description, color, options.fields || [], { ...options, author, guild });
      if (options.user?.displayAvatarURL && options.user?.id !== author?.id) embed.setThumbnail(options.user.displayAvatarURL());
      await channel.send(embedPayload(embed, { ...options, author, guild, defaultButtons: options.defaultButtons ?? false }));
      await this.db.arecord_livefeed_event(guild.id, moduleKey, { title, description, color, channel_id: String(channelId), user_id: options.user?.id || null }).catch(() => null);
      return true;
    } catch (error) {
      devPrint(`Log konnte nicht gesendet werden: ${error.message}`, 'debug', 'Logging');
      return false;
    }
  }

  async log_action(guild, title, description, color = COLOR_PRIMARY, options = {}) {
    return this.logAction(guild, title, description, color, options);
  }

  uptime() {
    return getUptime(this.startTime);
  }
}

module.exports = { ModForge, Tracker };
