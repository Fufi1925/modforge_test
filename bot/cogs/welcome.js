const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getEmbed } = require('../embed_config');

function replaceVars(text, member) {
  return String(text || '').replaceAll('{mention}', `${member}`).replaceAll('{user}', String(member.user?.tag || member)).replaceAll('{server}', member.guild?.name || '');
}

async function sendWelcome(bot, member) {
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const welcome = cfg.welcome || {};
  if (!welcome.enabled || !welcome.channel_id) return;
  const channel = await member.guild.channels.fetch(welcome.channel_id).catch(() => null);
  if (!channel?.isTextBased?.()) return;
  const embed = getEmbed('welcome', { guild: member.guild, user: member, bot });
  if (welcome.embed_title) embed.setTitle(replaceVars(welcome.embed_title, member));
  if (welcome.embed_description) embed.setDescription(replaceVars(welcome.embed_description, member));
  await channel.send({ content: welcome.mention ? `${member}` : null, embeds: [embed] }).catch(() => null);
  if (welcome.dm_enabled && welcome.dm_description) {
    const dmEmbed = getEmbed('welcome', { guild: member.guild, user: member, bot }).setDescription(replaceVars(welcome.dm_description, member));
    await member.send({ embeds: [dmEmbed] }).catch(() => null);
  }
  for (const roleId of welcome.add_roles || []) await member.roles.add(roleId, 'Auto-Role bei Join').catch(() => null);
}

async function sendLeave(bot, member) {
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const leave = cfg.leave || {};
  if (!leave.enabled || !leave.channel_id) return;
  const channel = await member.guild.channels.fetch(leave.channel_id).catch(() => null);
  if (!channel?.isTextBased?.()) return;
  const embed = getEmbed('leave', { guild: member.guild, user: member, bot });
  if (leave.embed_title) embed.setTitle(replaceVars(leave.embed_title, member));
  if (leave.embed_description) embed.setDescription(replaceVars(leave.embed_description, member));
  await channel.send({ embeds: [embed] }).catch(() => null);
}

async function restoreStickyRoles(bot, member) {
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const sticky = cfg.sticky_roles || [];
  if (!sticky.length) return;
  const doc = await bot.db.data.findOne({ guild_id: Number(member.guild.id), user_id: String(member.id), type: 'sticky_roles' }).catch(() => null);
  if (doc?.roles) for (const roleId of doc.roles) if (sticky.includes(roleId)) await member.roles.add(roleId, 'Sticky-Role wiederhergestellt').catch(() => null);
}

const commands = [{
  data: new SlashCommandBuilder().setName('welcome_channel').setDescription('Setzt den Welcome-Kanal')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
    .addChannelOption(o => o.setName('channel').setDescription('Der Kanal').setRequired(true)),
  async execute(bot, interaction) {
    const channel = interaction.options.getChannel('channel', true);
    const cfg = await bot.db.fetchConfig(interaction.guild.id);
    cfg.welcome = cfg.welcome || {};
    cfg.welcome.channel_id = channel.id;
    cfg.welcome.enabled = true;
    await bot.db.setConfig(interaction.guild.id, cfg);
    await interaction.reply({ content: `✅ Welcome-Kanal auf ${channel} gesetzt.`, ephemeral: true });
  }
}];

const events = [
  { name: 'guildMemberAdd', async execute(bot, member) { await restoreStickyRoles(bot, member); await sendWelcome(bot, member); } },
  { name: 'guildMemberRemove', async execute(bot, member) { await sendLeave(bot, member); } },
];

module.exports = { commands, events, sendWelcome, sendLeave, restoreStickyRoles };
