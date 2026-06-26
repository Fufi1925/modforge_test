const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { parseDuration, parseDurationMs, canModerate } = require('../utils');
const { getEmbed } = require('../embed_config');

async function sendDm(user, embedName, data) {
  try { await user.send({ embeds: [getEmbed(embedName, data)] }); } catch {}
}

async function createCase(bot, guildId, userId, modId, action, reason, duration = null) {
  return bot.db.acreate_case(guildId, userId, modId, action, reason, duration);
}

function moderationGuard(interaction, member) {
  const actor = interaction.member;
  const botMember = interaction.guild.members.me;
  return canModerate(actor, member, botMember);
}

const commands = [
  {
    data: new SlashCommandBuilder().setName('ban').setDescription('Bannt einen User')
      .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers)
      .addUserOption(o => o.setName('user').setDescription('Der zu bannende User').setRequired(true))
      .addStringOption(o => o.setName('reason').setDescription('Grund').setRequired(false)),
    async execute(bot, interaction) {
      const user = interaction.options.getUser('user', true);
      const member = await interaction.guild.members.fetch(user.id).catch(() => null);
      const reason = interaction.options.getString('reason') || 'Kein Grund';
      const [ok, msg] = moderationGuard(interaction, member);
      if (!ok) return interaction.reply({ embeds: [getEmbed('error', { message: msg || 'Du kannst diesen User nicht moderieren.', user: interaction.user, bot })], ephemeral: true });
      try {
        await member.ban({ reason });
        await createCase(bot, interaction.guild.id, user.id, interaction.user.id, 'ban', reason);
        const embed = getEmbed('ban', { user: member, mod: interaction.user, reason, guild: interaction.guild, bot });
        await interaction.reply({ embeds: [embed] });
        await sendDm(user, 'ban', { user, mod: interaction.user, reason, guild: interaction.guild, bot });
        await bot.db.arecord_guild_event(interaction.guild.id, 'ban', { guild_name: interaction.guild.name, member_count: interaction.guild.memberCount, user_id: user.id });
      } catch (e) { await interaction.reply({ embeds: [getEmbed('error', { message: `Fehler: ${e.message}`, user: interaction.user, bot })], ephemeral: true }).catch(() => null); }
    }
  },
  {
    data: new SlashCommandBuilder().setName('kick').setDescription('Kickt einen User')
      .setDefaultMemberPermissions(PermissionFlagsBits.KickMembers)
      .addUserOption(o => o.setName('user').setDescription('Der zu kickende User').setRequired(true))
      .addStringOption(o => o.setName('reason').setDescription('Grund').setRequired(false)),
    async execute(bot, interaction) {
      const user = interaction.options.getUser('user', true);
      const member = await interaction.guild.members.fetch(user.id).catch(() => null);
      const reason = interaction.options.getString('reason') || 'Kein Grund';
      const [ok, msg] = moderationGuard(interaction, member);
      if (!ok) return interaction.reply({ embeds: [getEmbed('error', { message: msg || 'Du kannst diesen User nicht moderieren.', user: interaction.user, bot })], ephemeral: true });
      try {
        await member.kick(reason);
        await createCase(bot, interaction.guild.id, user.id, interaction.user.id, 'kick', reason);
        const embed = getEmbed('kick', { user: member, mod: interaction.user, reason, guild: interaction.guild, bot });
        await interaction.reply({ embeds: [embed] });
        await sendDm(user, 'kick', { user, mod: interaction.user, reason, guild: interaction.guild, bot });
      } catch (e) { await interaction.reply({ embeds: [getEmbed('error', { message: `Fehler: ${e.message}`, user: interaction.user, bot })], ephemeral: true }).catch(() => null); }
    }
  },
  {
    data: new SlashCommandBuilder().setName('warn').setDescription('Verwarnt einen User')
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
      .addUserOption(o => o.setName('user').setDescription('Der zu warnende User').setRequired(true))
      .addStringOption(o => o.setName('reason').setDescription('Grund').setRequired(false)),
    async execute(bot, interaction) {
      const user = interaction.options.getUser('user', true);
      const member = await interaction.guild.members.fetch(user.id).catch(() => null);
      const reason = interaction.options.getString('reason') || 'Kein Grund';
      const [ok, msg] = moderationGuard(interaction, member);
      if (!ok) return interaction.reply({ embeds: [getEmbed('error', { message: msg || 'Du kannst diesen User nicht moderieren.', user: interaction.user, bot })], ephemeral: true });
      await createCase(bot, interaction.guild.id, user.id, interaction.user.id, 'warn', reason);
      const embed = getEmbed('warn', { user: member, mod: interaction.user, reason, guild: interaction.guild, bot });
      await interaction.reply({ embeds: [embed] });
      await sendDm(user, 'warn', { user, mod: interaction.user, reason, guild: interaction.guild, bot });
    }
  },
  {
    data: new SlashCommandBuilder().setName('mute').setDescription('Mutet einen User')
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
      .addUserOption(o => o.setName('user').setDescription('Der zu mutende User').setRequired(true))
      .addStringOption(o => o.setName('duration').setDescription('Dauer (z.B. 1h, 30m)').setRequired(false))
      .addStringOption(o => o.setName('reason').setDescription('Grund').setRequired(false)),
    async execute(bot, interaction) {
      const user = interaction.options.getUser('user', true);
      const member = await interaction.guild.members.fetch(user.id).catch(() => null);
      const duration = interaction.options.getString('duration') || '1h';
      const reason = interaction.options.getString('reason') || 'Kein Grund';
      const [ok, msg] = moderationGuard(interaction, member);
      if (!ok) return interaction.reply({ embeds: [getEmbed('error', { message: msg || 'Du kannst diesen User nicht moderieren.', user: interaction.user, bot })], ephemeral: true });
      const seconds = parseDuration(duration);
      if (!seconds) return interaction.reply({ embeds: [getEmbed('error', { message: 'Ungültige Dauer.', user: interaction.user, bot })], ephemeral: true });
      try {
        await member.timeout(seconds * 1000, reason);
        await createCase(bot, interaction.guild.id, user.id, interaction.user.id, 'mute', reason, seconds);
        const embed = getEmbed('mute', { user: member, mod: interaction.user, reason, duration, guild: interaction.guild, bot });
        await interaction.reply({ embeds: [embed] });
        await sendDm(user, 'mute', { user, mod: interaction.user, reason, duration, guild: interaction.guild, bot });
      } catch (e) { await interaction.reply({ embeds: [getEmbed('error', { message: `Fehler: ${e.message}`, user: interaction.user, bot })], ephemeral: true }).catch(() => null); }
    }
  },
  {
    data: new SlashCommandBuilder().setName('unmute').setDescription('Entfernt den Timeout eines Users')
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
      .addUserOption(o => o.setName('user').setDescription('Der User').setRequired(true)),
    async execute(bot, interaction) {
      const user = interaction.options.getUser('user', true);
      const member = await interaction.guild.members.fetch(user.id).catch(() => null);
      const [ok, msg] = moderationGuard(interaction, member);
      if (!ok) return interaction.reply({ embeds: [getEmbed('error', { message: msg || 'Du kannst diesen User nicht moderieren.', user: interaction.user, bot })], ephemeral: true });
      try {
        await member.timeout(null, 'Timeout entfernt');
        const embed = getEmbed('success', { message: `Timeout von ${member} wurde entfernt.`, user: member, bot });
        await interaction.reply({ embeds: [embed] });
        await sendDm(user, 'success', { message: 'Dein Timeout wurde entfernt.', user, bot });
      } catch (e) { await interaction.reply({ embeds: [getEmbed('error', { message: `Fehler: ${e.message}`, user: interaction.user, bot })], ephemeral: true }).catch(() => null); }
    }
  },
];

module.exports = { commands };
