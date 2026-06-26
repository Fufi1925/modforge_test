const { AuditLogEvent } = require('discord.js');
const { createEmbed, embedPayload } = require('../utils');
const { COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, ACTIVITY } = require('../config');

const SUSPICIOUS_NAME_REGEX = /^(user|discord|admin|mod|support)[0-9_\-]{2,}$/i;
const MAX_TIMEOUT_MS = 2_147_000_000;

function formatUntil(ts) {
  if (!ts) return 'Unbekannt';
  const diff = Math.max(0, ts - Date.now());
  const minutes = Math.ceil(diff / 60000);
  if (minutes < 60) return `${minutes} Minuten`;
  const hours = Math.ceil(minutes / 60);
  if (hours < 24) return `${hours} Stunden`;
  return `${Math.ceil(hours / 24)} Tage`;
}

async function safeUserDm(bot, guild, user, title, description, color = COLOR_PRIMARY, type = 'moderation', author = null) {
  if (!user || user.bot) return false;
  const dedupeKey = `${guild.id}:${user.id}:${type}:${title}:${description}`.slice(0, 500);
  bot.dmDedupe = bot.dmDedupe || new Map();
  const last = bot.dmDedupe.get(dedupeKey) || 0;
  if (Date.now() - last < 120000) return false;
  try {
    const recent = await bot.db.data.findOne({ type: 'moderation_dm', dedupe_key: dedupeKey, created_at: { $gte: new Date(Date.now() - 120000) } }).catch(() => null);
    if (recent) return false;
  } catch {}
  bot.dmDedupe.set(dedupeKey, Date.now());
  const embed = createEmbed(title, description, color, [], { author: author || bot.user, guild });
  try {
    await user.send(embedPayload(embed, { author: author || bot.user, guild }));
    await bot.db.data.insertOne({
      type: 'moderation_dm',
      guild_id: Number(guild.id),
      user_id: String(user.id),
      dm_type: type,
      title,
      description,
      dedupe_key: dedupeKey,
      sent: true,
      created_at: new Date(),
    }).catch(() => null);
    return true;
  } catch (error) {
    await bot.db.data.insertOne({
      type: 'moderation_dm',
      guild_id: Number(guild.id),
      user_id: String(user.id),
      dm_type: type,
      title,
      description,
      dedupe_key: dedupeKey,
      sent: false,
      error: error.message,
      created_at: new Date(),
    }).catch(() => null);
    return false;
  }
}

async function latestAudit(guild, type, targetId = null, maxAgeMs = 15000) {
  try {
    const logs = await guild.fetchAuditLogs({ type, limit: 8 });
    const now = Date.now();
    return logs.entries.find((entry) => {
      const targetOk = targetId == null || String(entry.target?.id || entry.targetId || '') === String(targetId);
      const fresh = now - entry.createdTimestamp <= maxAgeMs;
      return targetOk && fresh;
    }) || null;
  } catch {
    return null;
  }
}

function roleChangeDedupe(bot, guildId, key) {
  bot.roleLogDedupe = bot.roleLogDedupe || new Map();
  const full = `${guildId}:${key}`;
  const last = bot.roleLogDedupe.get(full) || 0;
  if (Date.now() - last < 5000) return true;
  bot.roleLogDedupe.set(full, Date.now());
  return false;
}

function permText(bitfield) {
  try { return BigInt(bitfield || 0).toString(); } catch { return String(bitfield || 0); }
}

function scheduleTimeoutExpiryDm(bot, member, untilTs, reason = 'Timeout abgelaufen') {
  if (!untilTs || untilTs <= Date.now()) return;
  bot.timeoutDmTimers = bot.timeoutDmTimers || new Map();
  const key = `${member.guild.id}:${member.id}`;
  const old = bot.timeoutDmTimers.get(key);
  if (old) clearTimeout(old);
  const delay = Math.min(MAX_TIMEOUT_MS, Math.max(1000, untilTs - Date.now() + 1500));
  const timer = setTimeout(async () => {
    const fresh = await member.guild.members.fetch(member.id).catch(() => null);
    if (!fresh) return;
    const stillTimed = fresh.communicationDisabledUntilTimestamp && fresh.communicationDisabledUntilTimestamp > Date.now();
    if (stillTimed) return scheduleTimeoutExpiryDm(bot, fresh, fresh.communicationDisabledUntilTimestamp, reason);
    await safeUserDm(
      bot,
      fresh.guild,
      fresh.user,
      '🔊 Timeout abgelaufen',
      `**Server:** ${fresh.guild.name}\nDein Timeout ist abgelaufen. Du kannst wieder schreiben.`,
      COLOR_SUCCESS,
      'timeout_expired',
      bot.user,
    );
    await bot.db.data.updateOne({ type: 'timeout_expiry_dm', guild_id: Number(fresh.guild.id), user_id: String(fresh.id) }, { $set: { sent_at: new Date(), active: false } }).catch(() => null);
    bot.timeoutDmTimers.delete(key);
  }, delay);
  bot.timeoutDmTimers.set(key, timer);
  bot.db.data.updateOne(
    { type: 'timeout_expiry_dm', guild_id: Number(member.guild.id), user_id: String(member.id) },
    { $set: { until: new Date(untilTs), reason, active: true, updated_at: new Date() }, $setOnInsert: { created_at: new Date() } },
    { upsert: true },
  ).catch(() => null);
}

const events = [
  {
    name: 'clientReady',
    async execute(bot) {
      for (const guild of bot.guilds.cache.values()) {
        try {
          const members = await guild.members.fetch();
          for (const member of members.values()) {
            if (member.user.bot) continue;
            const until = member.communicationDisabledUntilTimestamp;
            if (until && until > Date.now()) scheduleTimeoutExpiryDm(bot, member, until, 'Beim Bot-Start aus Discord gelesen');
          }
        } catch (error) {
          // Wenn Members Intent/Rechte fehlen, läuft der Bot weiter; neue Timeout-Events werden trotzdem erfasst.
        }
      }
    }
  },
  {
    name: 'guildMemberAdd',
    async execute(bot, member) {
      const guild = member.guild;
      const cfg = await bot.db.fetchConfig(guild.id);
      const secLevel = cfg.security_level || 0;
      const raidCfg = cfg.anti_raid || {};
      ACTIVITY.push('join', `${member} ist **${guild.name}** beigetreten (${guild.memberCount} Member).`, { guild_id: guild.id, guild_name: guild.name, user_id: member.id, user_name: String(member) });
      if (bot.isWhitelisted(member, 'bypass_antinuke')) {
        await bot.logAction(guild, '➕ Mitglied beigetreten', `${member}`, COLOR_SUCCESS, { user: member, module: 'members' });
        return;
      }

      const vpnCfg = cfg.anti_vpn || {};
      if (vpnCfg.enabled && !member.user.bot) {
        const vpnWl = (vpnCfg.whitelist_ids || []).map(String);
        const ageH = (Date.now() - member.user.createdTimestamp) / 3600000;
        if (!vpnWl.includes(String(member.id)) && ageH < 24 && !member.user.avatar && (member.user.username.startsWith('user') || member.user.username.length < 4)) {
          try {
            if ((vpnCfg.action || 'kick') === 'ban') await member.ban({ reason: 'Anti-VPN: Verdächtiger Account' });
            else await member.kick('Anti-VPN: Verdächtiger Account');
            await bot.logAction(guild, '🛡️ Anti-VPN', `${member} – ${Math.floor(ageH)}h alt`, COLOR_WARNING, { user: member, module: 'antiraid' });
            return;
          } catch {}
        }
      }

      if (secLevel >= 2) {
        const age = Math.floor((Date.now() - member.user.createdTimestamp) / 86400000);
        if (age < 5) {
          try {
            await member.kick('Sicherheitsstufe 2: Account zu jung');
            await bot.logAction(guild, '🛡️ Stufe 2: Kick', `${member} (${age} Tage)`, COLOR_DANGER, { user: member, module: 'antiraid' });
            return;
          } catch {}
        }
      }
      if (secLevel >= 3) {
        try { await member.ban({ reason: 'Sicherheitsstufe 3: BLACKOUT aktiv' }); return; } catch {}
      }

      if (raidCfg.enabled) {
        const key = guild.id;
        const now = Date.now();
        const dq = bot.tracker.raidTracker.get(key) || [];
        dq.push(now);
        while (dq.length && now - dq[0] > (raidCfg.window || 20) * 1000) dq.shift();
        bot.tracker.raidTracker.set(key, dq);
        const minAge = raidCfg.min_account_age || 7;
        const age = Math.floor((Date.now() - member.user.createdTimestamp) / 86400000);
        if (age < minAge && raidCfg.auto_kick) {
          try {
            await member.kick(`Anti-Raid: Account zu jung (${age}d)`);
            await bot.logAction(guild, '🆕 Account gekickt', `${member} (${age}d)`, COLOR_DANGER, { user: member, module: 'antiraid' });
            return;
          } catch {}
        }
        if (raidCfg.suspicious_name_check && SUSPICIOUS_NAME_REGEX.test(member.user.username)) {
          await bot.logAction(guild, '🚨 Verdächtiger Name', `${member} (\`${member.user.username}\`)`, COLOR_WARNING, { user: member, module: 'antiraid' });
        }
        if (dq.length === Math.max(1, (raidCfg.join_threshold || 10) - 2)) {
          await bot.logAction(guild, '💡 Smart Anti-Raid Vorschlag', 'Viele neue Beitritte erkannt → Anti-Raid eventuell höher stellen oder Lockdown aktivieren.', COLOR_WARNING, { user: member, module: 'antiraid' });
        }
        if (dq.length >= (raidCfg.join_threshold || 10)) {
          bot.tracker.raidTracker.set(key, []);
          if (!bot.tracker.lockdownActive.get(guild.id) && raidCfg.lockdown) {
            bot.tracker.lockdownActive.set(guild.id, true);
            for (const channel of guild.channels.cache.values()) {
              if (channel.isTextBased?.()) await channel.permissionOverwrites.edit(guild.roles.everyone, { SendMessages: false }, { reason: 'Anti-Raid Lockdown' }).catch(() => null);
            }
            await bot.logAction(guild, '🔒 LOCKDOWN AKTIVIERT', 'Alle Kanäle gesperrt.', COLOR_DANGER, { module: 'antiraid' });
          }
          await bot.logAction(guild, '💥 RAID ERKANNT', 'Zu viele Beitritte!', COLOR_DANGER, { module: 'antiraid' });
        }
      }
    }
  },
  {
    name: 'guildMemberUpdate',
    async execute(bot, before, after) {
      if (!after.guild || after.user?.bot) return;
      const beforeUntil = before.communicationDisabledUntilTimestamp || 0;
      const afterUntil = after.communicationDisabledUntilTimestamp || 0;
      if (afterUntil && afterUntil !== beforeUntil && afterUntil > Date.now()) {
        const audit = await latestAudit(after.guild, AuditLogEvent.MemberUpdate, after.id);
        const executor = audit?.executor || null;
        const reason = audit?.reason || 'Kein Grund angegeben';
        const duration = formatUntil(afterUntil);
        scheduleTimeoutExpiryDm(bot, after, afterUntil, reason);
        if (!executor || executor.id !== bot.user?.id) {
          await safeUserDm(
            bot,
            after.guild,
            after.user,
            '🔇 Du wurdest getimeoutet',
            `**Server:** ${after.guild.name}\n**Von:** ${executor ? `${executor.tag || executor.username}` : 'Unbekannt'}\n**Dauer:** ${duration}\n**Grund:** ${reason}`,
            COLOR_WARNING,
            'timeout_start',
            executor || bot.user,
          );
        }
        await bot.logAction(after.guild, '🔇 Timeout gesetzt', `**User:** ${after} (\`${after.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Dauer:** ${duration}\n**Grund:** ${reason}`, COLOR_WARNING, { module: 'moderation', user: after.user, executor: executor || bot.user });
      }
      if (beforeUntil && beforeUntil > Date.now() && (!afterUntil || afterUntil <= Date.now())) {
        const audit = await latestAudit(after.guild, AuditLogEvent.MemberUpdate, after.id);
        const executor = audit?.executor || null;
        const manual = audit && audit.createdTimestamp > Date.now() - 15000;
        if (manual && (!executor || executor.id !== bot.user?.id)) {
          await safeUserDm(
            bot,
            after.guild,
            after.user,
            '🔊 Timeout aufgehoben',
            `**Server:** ${after.guild.name}\n**Aufgehoben von:** ${executor ? `${executor.tag || executor.username}` : 'Unbekannt'}\n**Grund:** ${audit?.reason || 'Kein Grund angegeben'}`,
            COLOR_SUCCESS,
            'timeout_removed',
            executor || bot.user,
          );
          await bot.logAction(after.guild, '🔊 Timeout aufgehoben', `**User:** ${after} (\`${after.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${audit?.reason || 'Kein Grund angegeben'}`, COLOR_SUCCESS, { module: 'moderation', user: after.user, executor: executor || bot.user });
        } else if (Date.now() >= beforeUntil - 5000) {
          await safeUserDm(
            bot,
            after.guild,
            after.user,
            '🔊 Timeout abgelaufen',
            `**Server:** ${after.guild.name}\nDein Timeout ist abgelaufen. Du kannst wieder schreiben.`,
            COLOR_SUCCESS,
            'timeout_expired',
            bot.user,
          );
        }
      }

      // Rollen geben/nehmen sauber loggen – mit Audit-Log Executor, kein Doppel-Log.
      const beforeRoles = new Set(before.roles.cache.keys());
      const afterRoles = new Set(after.roles.cache.keys());
      const added = [...afterRoles].filter((id) => !beforeRoles.has(id));
      const removed = [...beforeRoles].filter((id) => !afterRoles.has(id));
      if (added.length || removed.length) {
        const audit = await latestAudit(after.guild, AuditLogEvent.MemberRoleUpdate, after.id, 20000);
        const executor = audit?.executor || bot.user;
        for (const roleId of added) {
          const role = after.guild.roles.cache.get(roleId);
          if (!role || role.id === after.guild.id) continue;
          const key = `member-role-add:${after.id}:${role.id}:${audit?.id || ''}`;
          if (roleChangeDedupe(bot, after.guild.id, key)) continue;
          await bot.logAction(after.guild, '🏷️ Rolle gegeben', `**User:** ${after} (\`${after.id}\`)\n**Rolle:** ${role} (\`${role.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${audit?.reason || 'Kein Grund angegeben'}`, COLOR_SUCCESS, { module: 'roles', user: after.user, executor });
        }
        for (const roleId of removed) {
          const role = before.guild.roles.cache.get(roleId) || { id: roleId, name: roleId, toString: () => `@${roleId}` };
          if (role.id === before.guild.id) continue;
          const key = `member-role-remove:${after.id}:${role.id}:${audit?.id || ''}`;
          if (roleChangeDedupe(bot, after.guild.id, key)) continue;
          await bot.logAction(after.guild, '🏷️ Rolle entfernt', `**User:** ${after} (\`${after.id}\`)\n**Rolle:** ${role} (\`${role.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${audit?.reason || 'Kein Grund angegeben'}`, COLOR_WARNING, { module: 'roles', user: after.user, executor });
        }
      }
    }
  },
  { name: 'messageDelete', async execute(bot, message) { if (!message.guild || message.author?.bot) return; bot.tracker.ghostTracker.set(`${message.guild.id}:${message.channel.id}`, { author: message.author?.tag, content: message.content, ts: Date.now() }); await bot.db.amark_message_deleted(message.guild.id, message.id).catch(() => null); await bot.logAction(message.guild, '🗑️ Nachricht gelöscht', `Autor: ${message.author}\nKanal: ${message.channel}\nInhalt: ${String(message.content || '').slice(0, 1000)}`, COLOR_WARNING, { module: 'messages' }); } },
  { name: 'messageUpdate', async execute(bot, before, after) { if (!before.guild || before.author?.bot || before.content === after.content) return; await bot.db.aappend_message_edit(before.guild.id, before.id, before.content || '', after.content || '').catch(() => null); await bot.logAction(before.guild, '✏️ Nachricht bearbeitet', `Autor: ${before.author}\nKanal: ${before.channel}\nVorher: ${String(before.content || '').slice(0, 500)}\nNachher: ${String(after.content || '').slice(0, 500)}`, COLOR_WARNING, { module: 'messages' }); } },
  { name: 'messageCreate', async execute(bot, message) { if (!message.guild || message.author?.bot) return; await bot.db.arecord_message(message.guild.id, message).catch(() => null); } },
  {
    name: 'guildMemberRemove',
    async execute(bot, member) {
      ACTIVITY.push('member_leave', `${member.user.tag} hat ${member.guild.name} verlassen.`);
      const kickAudit = await latestAudit(member.guild, AuditLogEvent.MemberKick, member.id);
      if (kickAudit) {
        const executor = kickAudit.executor || null;
        const reason = kickAudit.reason || 'Kein Grund angegeben';
        if (!executor || executor.id !== bot.user?.id) {
          await safeUserDm(bot, member.guild, member.user, '👢 Du wurdest gekickt', `**Server:** ${member.guild.name}\n**Von:** ${executor ? `${executor.tag || executor.username}` : 'Unbekannt'}\n**Grund:** ${reason}`, COLOR_WARNING, 'kick', executor || bot.user);
        }
        await bot.logAction(member.guild, '👢 Member gekickt', `**User:** ${member.user.tag} (\`${member.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${reason}`, COLOR_WARNING, { module: 'moderation', user: member.user, executor: executor || bot.user });
      } else {
        await bot.logAction(member.guild, '➖ Member verlassen', `${member.user.tag} hat den Server verlassen.`, COLOR_WARNING, { module: 'members', user: member.user });
      }
    }
  },
  { name: 'guildCreate', async execute(bot, guild) { ACTIVITY.push('guild_join', `ModForge wurde zu ${guild.name} hinzugefügt.`); } },
  { name: 'guildDelete', async execute(bot, guild) { ACTIVITY.push('guild_remove', `ModForge wurde von ${guild.name} entfernt.`); } },
  {
    name: 'guildBanAdd',
    async execute(bot, ban) {
      const audit = await latestAudit(ban.guild, AuditLogEvent.MemberBanAdd, ban.user.id);
      const executor = audit?.executor || null;
      const reason = audit?.reason || 'Kein Grund angegeben';
      if (!executor || executor.id !== bot.user?.id) {
        await safeUserDm(bot, ban.guild, ban.user, '🔨 Du wurdest gebannt', `**Server:** ${ban.guild.name}\n**Von:** ${executor ? `${executor.tag || executor.username}` : 'Unbekannt'}\n**Grund:** ${reason}`, COLOR_DANGER, 'ban', executor || bot.user);
      }
      await bot.logAction(ban.guild, '🔨 Member gebannt', `**User:** ${ban.user.tag} (\`${ban.user.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${reason}`, COLOR_DANGER, { module: 'moderation', user: ban.user, executor: executor || bot.user });
    }
  },
  {
    name: 'guildBanRemove',
    async execute(bot, ban) {
      const audit = await latestAudit(ban.guild, AuditLogEvent.MemberBanRemove, ban.user.id);
      const executor = audit?.executor || null;
      const reason = audit?.reason || 'Kein Grund angegeben';
      await safeUserDm(bot, ban.guild, ban.user, '⚖️ Du wurdest entbannt', `**Server:** ${ban.guild.name}\n**Von:** ${executor ? `${executor.tag || executor.username}` : 'Unbekannt'}\n**Grund:** ${reason}`, COLOR_SUCCESS, 'unban', executor || bot.user);
      await bot.logAction(ban.guild, '⚖️ Member entbannt', `**User:** ${ban.user.tag} (\`${ban.user.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${reason}`, COLOR_SUCCESS, { module: 'moderation', user: ban.user, executor: executor || bot.user });
    }
  },
  { name: 'channelCreate', async execute(bot, channel) { if (channel.guild) await bot.logAction(channel.guild, '📁 Channel erstellt', `${channel} wurde erstellt.`, COLOR_WARNING, { module: 'channels' }); } },
  { name: 'channelDelete', async execute(bot, channel) { if (channel.guild) await bot.logAction(channel.guild, '📁 Channel gelöscht', `**${channel.name}** wurde gelöscht.`, COLOR_WARNING, { module: 'channels' }); } },
  {
    name: 'roleCreate',
    async execute(bot, role) {
      const audit = await latestAudit(role.guild, AuditLogEvent.RoleCreate, role.id, 20000);
      const executor = audit?.executor || bot.user;
      const key = `role-create:${role.id}:${audit?.id || ''}`;
      if (roleChangeDedupe(bot, role.guild.id, key)) return;
      await bot.logAction(role.guild, '🏷️ Rolle erstellt', `**Rolle:** ${role} (\`${role.id}\`)\n**Name:** ${role.name}\n**Farbe:** ${role.hexColor}\n**Position:** ${role.position}\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${audit?.reason || 'Kein Grund angegeben'}`, COLOR_SUCCESS, { module: 'roles', executor });
    }
  },
  {
    name: 'roleDelete',
    async execute(bot, role) {
      const audit = await latestAudit(role.guild, AuditLogEvent.RoleDelete, role.id, 20000);
      const executor = audit?.executor || bot.user;
      const key = `role-delete:${role.id}:${audit?.id || ''}`;
      if (roleChangeDedupe(bot, role.guild.id, key)) return;
      await bot.logAction(role.guild, '🏷️ Rolle gelöscht', `**Rolle:** **${role.name}** (\`${role.id}\`)\n**Farbe:** ${role.hexColor || 'Keine'}\n**Position:** ${role.position}\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${audit?.reason || 'Kein Grund angegeben'}`, COLOR_DANGER, { module: 'roles', executor });
    }
  },
  {
    name: 'roleUpdate',
    async execute(bot, before, after) {
      const changes = [];
      if (before.name !== after.name) changes.push(`**Name:** ${before.name} → ${after.name}`);
      if (before.hexColor !== after.hexColor) changes.push(`**Farbe:** ${before.hexColor} → ${after.hexColor}`);
      if (before.position !== after.position) changes.push(`**Höhe/Position:** ${before.position} → ${after.position}`);
      const beforePerm = permText(before.permissions?.bitfield);
      const afterPerm = permText(after.permissions?.bitfield);
      if (beforePerm !== afterPerm) changes.push(`**Rechte:** \`${beforePerm}\` → \`${afterPerm}\``);
      if (before.hoist !== after.hoist) changes.push(`**Separat anzeigen:** ${before.hoist ? 'Ja' : 'Nein'} → ${after.hoist ? 'Ja' : 'Nein'}`);
      if (before.mentionable !== after.mentionable) changes.push(`**Erwähnbar:** ${before.mentionable ? 'Ja' : 'Nein'} → ${after.mentionable ? 'Ja' : 'Nein'}`);
      if (!changes.length) return;
      const audit = await latestAudit(after.guild, AuditLogEvent.RoleUpdate, after.id, 20000);
      const executor = audit?.executor || bot.user;
      const key = `role-update:${after.id}:${changes.join('|')}:${audit?.id || ''}`;
      if (roleChangeDedupe(bot, after.guild.id, key)) return;
      await bot.logAction(after.guild, '🏷️ Rolle geändert', `**Rolle:** ${after} (\`${after.id}\`)\n**Von:** ${executor ? `${executor}` : 'Unbekannt'}\n**Grund:** ${audit?.reason || 'Kein Grund angegeben'}\n\n${changes.join('\n')}`, COLOR_WARNING, { module: 'roles', executor });
    }
  },
  {
    name: 'voiceStateUpdate',
    async execute(bot, oldState, newState) {
      const state = newState || oldState;
      const guild = state.guild;
      const member = state.member || oldState.member || newState.member;
      if (!guild || !member || member.user?.bot) return;
      const userText = `${member} (\`${member.id}\`)`;
      const oldCh = oldState.channel;
      const newCh = newState.channel;
      let title = null;
      let desc = null;
      let color = COLOR_WARNING;
      if (!oldCh && newCh) {
        title = '🔊 Voice beigetreten';
        desc = `**User:** ${userText}\n**Channel:** ${newCh}`;
        color = COLOR_SUCCESS;
      } else if (oldCh && !newCh) {
        title = '🔇 Voice verlassen';
        desc = `**User:** ${userText}\n**Channel:** ${oldCh}`;
        color = COLOR_WARNING;
      } else if (oldCh && newCh && oldCh.id !== newCh.id) {
        title = '🔁 Voice gewechselt';
        desc = `**User:** ${userText}\n**Von:** ${oldCh}\n**Nach:** ${newCh}`;
        color = COLOR_PRIMARY;
      } else {
        const changes = [];
        if (oldState.selfMute !== newState.selfMute) changes.push(`Self-Mute: **${newState.selfMute ? 'an' : 'aus'}**`);
        if (oldState.selfDeaf !== newState.selfDeaf) changes.push(`Self-Deaf: **${newState.selfDeaf ? 'an' : 'aus'}**`);
        if (oldState.serverMute !== newState.serverMute) changes.push(`Server-Mute: **${newState.serverMute ? 'an' : 'aus'}**`);
        if (oldState.serverDeaf !== newState.serverDeaf) changes.push(`Server-Deaf: **${newState.serverDeaf ? 'an' : 'aus'}**`);
        if (oldState.streaming !== newState.streaming) changes.push(`Streaming: **${newState.streaming ? 'an' : 'aus'}**`);
        if (oldState.selfVideo !== newState.selfVideo) changes.push(`Kamera: **${newState.selfVideo ? 'an' : 'aus'}**`);
        if (oldState.suppress !== newState.suppress) changes.push(`Suppress: **${newState.suppress ? 'an' : 'aus'}**`);
        if (!changes.length) return;
        title = '🎙️ Voice-Status geändert';
        desc = `**User:** ${userText}\n**Channel:** ${newCh || oldCh}\n${changes.join('\n')}`;
        color = COLOR_PRIMARY;
      }
      ACTIVITY.push('voice', `${member.user.tag} – ${title}`, { guild_id: guild.id, guild_name: guild.name, user_id: member.id, user_name: member.user.tag });
      await bot.db.arecord_livefeed_event(guild.id, 'voice', { title, description: desc, user_id: String(member.id), old_channel_id: oldCh?.id || null, new_channel_id: newCh?.id || null }).catch(() => null);
      await bot.logAction(guild, title, desc, color, { module: 'voice', user: member.user });
    }
  },
];
module.exports = { events };
