// bot/utils.js – Hilfsfunktionen für ModForge Node.js Migration
const { EmbedBuilder, AttachmentBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');
const { AsyncLocalStorage } = require('node:async_hooks');
const { COLOR_PRIMARY, COLOR_DANGER, COLOR_SUCCESS, FOOTER_TEXT, FOOTER_ICON, SCAM_DOMAINS, URL_SHORTENERS } = require('./config');

const embedContext = new AsyncLocalStorage();

function runWithEmbedContext(context, fn) {
  return embedContext.run(context || {}, fn);
}

function getEmbedContext() {
  return embedContext.getStore() || {};
}

function avatarOf(user) {
  return user?.displayAvatarURL?.({ size: 128 }) || user?.displayAvatarURL?.() || user?.avatarURL?.({ size: 128 }) || user?.avatarURL?.() || user?.defaultAvatarURL || null;
}

function serverIconOf(guild, size = 256) {
  return guild?.iconURL?.({ size }) || guild?.iconURL?.() || null;
}

function serverBannerOf(guild, size = 1024) {
  return guild?.bannerURL?.({ size }) || guild?.bannerURL?.() || guild?.splashURL?.({ size }) || guild?.splashURL?.() || null;
}

function nameOf(user) {
  return user?.globalName || user?.displayName || user?.tag || user?.username || user?.user?.tag || user?.user?.username || 'ModForge';
}

function resolveAuthor(options = {}) {
  const ctx = getEmbedContext();
  const raw = options.author || options.executor || options.mod || options.actor || options.user || ctx.author || ctx.user || ctx.interaction?.user || null;
  if (!raw) return { name: 'ModForge', iconURL: FOOTER_ICON };
  if (raw.name && raw.iconURL) return { name: String(raw.name), iconURL: raw.iconURL };
  const user = raw.user || raw;
  return { name: nameOf(user), iconURL: avatarOf(user) || FOOTER_ICON };
}

function quoteDescription(description = '') {
  const text = String(description || '').trim();
  if (!text) return '';
  return text
    .split('\n')
    .map((line) => line.startsWith('>') ? line : `> ${line || '‎'}`)
    .join('\n')
    .slice(0, 4096);
}

function modernizeEmbed(embed, options = {}) {
  const data = embed.data || {};
  const author = resolveAuthor(options);
  const guild = options.guild || options.server || getEmbedContext().guild || getEmbedContext().interaction?.guild || null;
  if (!data.author && author?.name) embed.setAuthor({ name: author.name.slice(0, 256), iconURL: author.iconURL || undefined });
  if (typeof data.description === 'string') embed.setDescription(quoteDescription(data.description));
  // Rechts im Embed immer Server-Profil/Icon, wenn ein Server-Kontext existiert.
  if (!data.thumbnail && guild) {
    const icon = serverIconOf(guild);
    if (icon) embed.setThumbnail(icon);
  }
  // Optional großes Bild/Banner, nur wenn explizit gewünscht, damit Logs clean bleiben.
  if (!data.image && options.useServerBanner && guild) {
    const banner = serverBannerOf(guild);
    if (banner) embed.setImage(banner);
  }
  if (!data.footer) embed.setFooter({ text: guild?.name ? `${guild.name} • ModForge` : FOOTER_TEXT, iconURL: serverIconOf(guild, 128) || FOOTER_ICON });
  if (!data.timestamp) embed.setTimestamp(new Date());
  return embed;
}

function utcnow() {
  return new Date();
}

function toAwareUtc(value) {
  return value instanceof Date ? value : new Date(value || Date.now());
}

function createEmbed(title, description = '', color = COLOR_PRIMARY, fields = [], options = {}) {
  const embed = new EmbedBuilder()
    .setTitle(String(title || 'ModForge'))
    .setDescription(quoteDescription(description || ''))
    .setColor(color)
    .setFooter({ text: FOOTER_TEXT, iconURL: FOOTER_ICON })
    .setTimestamp(new Date());
  const author = resolveAuthor(options);
  if (author?.name) embed.setAuthor({ name: author.name.slice(0, 256), iconURL: author.iconURL || undefined });
  for (const field of fields || []) {
    if (Array.isArray(field)) embed.addFields({ name: String(field[0]), value: String(field[1]), inline: Boolean(field[2]) });
    else embed.addFields({ name: String(field.name), value: String(field.value), inline: Boolean(field.inline) });
  }
  if (options.thumbnail) embed.setThumbnail(options.thumbnail);
  if (options.image) embed.setImage(options.image);
  return modernizeEmbed(embed, options);
}

function normalizeButton(button) {
  if (!button) return null;
  const label = String(button.label || button.text || 'Öffnen').slice(0, 80);
  const emoji = button.emoji || undefined;
  if (button.url) return new ButtonBuilder().setStyle(ButtonStyle.Link).setLabel(label).setURL(String(button.url)).setEmoji(emoji);
  return new ButtonBuilder()
    .setStyle(button.style || ButtonStyle.Secondary)
    .setLabel(label)
    .setCustomId(String(button.customId || button.custom_id || `modforge:${label.toLowerCase().replace(/[^a-z0-9]+/g, '_')}`).slice(0, 100))
    .setEmoji(emoji)
    .setDisabled(Boolean(button.disabled));
}

function createButtonRows(buttons = []) {
  const normalized = (buttons || []).map(normalizeButton).filter(Boolean).slice(0, 25);
  const rows = [];
  for (let i = 0; i < normalized.length; i += 5) rows.push(new ActionRowBuilder().addComponents(normalized.slice(i, i + 5)));
  return rows;
}

function defaultEmbedButtons(options = {}) {
  const guild = options.guild || options.server || getEmbedContext().guild || getEmbedContext().interaction?.guild || null;
  const buttons = [];
  const dashboardBase = process.env.DASHBOARD_BASE_URL || process.env.PUBLIC_BASE_URL || '';
  if (dashboardBase && guild?.id) buttons.push({ label: 'Dashboard', emoji: '📊', url: `${dashboardBase.replace(/\/$/, '')}/dashboard/${guild.id}` });
  const icon = serverIconOf(guild, 512);
  if (icon) buttons.push({ label: 'Server Profil', emoji: '🏰', url: icon });
  return buttons;
}

function embedPayload(embed, options = {}) {
  const finalEmbed = modernizeEmbed(embed, options);
  const buttons = options.buttons === false ? [] : [...(options.buttons || []), ...(options.defaultButtons === false ? [] : defaultEmbedButtons(options))];
  const components = options.components || createButtonRows(buttons);
  return { embeds: [finalEmbed], ...(components.length ? { components } : {}) };
}

function successEmbed(title, description) {
  return createEmbed(title, description, COLOR_SUCCESS);
}

function errorEmbed(title, description) {
  return createEmbed(title, description, COLOR_DANGER);
}

function parseDuration(input = '1h') {
  const text = String(input || '').trim().toLowerCase();
  const match = text.match(/^(\d+)\s*([smhdw]?)$/);
  if (!match) return null;
  const value = Number(match[1]);
  const unit = match[2] || 's';
  const seconds = value * ({ s: 1, m: 60, h: 3600, d: 86400, w: 604800 }[unit] || 1);
  const maxSeconds = 60 * 60 * 24 * 28;
  return Math.min(seconds, maxSeconds);
}

function parseDurationMs(input = '1h') {
  const seconds = parseDuration(input);
  return seconds ? seconds * 1000 : null;
}

function canModerate(actor, target, botMember = null) {
  if (!actor || !target) return [false, 'User nicht gefunden.'];
  const guild = actor.guild || target.guild;
  const actorId = actor.id || actor.user?.id;
  const targetId = target.id || target.user?.id;
  const botId = botMember?.id || botMember?.user?.id;
  if (guild?.ownerId && targetId === guild.ownerId) return [false, 'Der Server-Owner kann nicht moderiert werden.'];
  if (botId && targetId === botId) return [false, 'Ich kann mich nicht selbst moderieren.'];
  if (targetId === actorId) return [false, 'Du kannst dich nicht selbst moderieren.'];
  if (guild?.ownerId && actorId !== guild.ownerId && actor.roles?.highest && target.roles?.highest && actor.roles.highest.comparePositionTo(target.roles.highest) <= 0) return [false, 'Deine höchste Rolle ist nicht über der des Ziels.'];
  if (botMember?.roles?.highest && target.roles?.highest && botMember.roles.highest.comparePositionTo(target.roles.highest) <= 0) return [false, 'Meine höchste Rolle ist nicht über der des Ziels.'];
  return [true, ''];
}

function formatDuration(ms) {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function normalizeDomain(url) {
  try {
    const parsed = new URL(url.startsWith('http') ? url : `https://${url}`);
    return parsed.hostname.toLowerCase().replace(/^www\./, '');
  } catch {
    return String(url || '').toLowerCase().replace(/^www\./, '');
  }
}

function checkPhishingUrl(content = '') {
  const urls = String(content).match(/https?:\/\/[^\s]+|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s]*)?/gi) || [];
  for (const url of urls) {
    const domain = normalizeDomain(url);
    if (SCAM_DOMAINS.some((bad) => domain === bad || domain.endsWith(`.${bad}`))) return { detected: true, reason: 'scam_domain', url, domain };
    if (URL_SHORTENERS.includes(domain)) return { detected: true, reason: 'url_shortener', url, domain };
  }
  return { detected: false };
}

function generateCaptcha(difficulty = 'medium') {
  const length = difficulty === 'hard' ? 6 : difficulty === 'easy' ? 4 : 5;
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let code = '';
  for (let i = 0; i < length; i++) code += chars[Math.floor(Math.random() * chars.length)];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="420" height="140"><rect width="100%" height="100%" fill="#0f172a"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" font-size="48" font-family="monospace" fill="#60a5fa" letter-spacing="8">${code}</text></svg>`;
  const attachment = new AttachmentBuilder(Buffer.from(svg), { name: 'captcha.svg' });
  return { code, attachment };
}

async function safeDm(user, embed, cooldownKey = null, cooldownSeconds = 30) {
  if (!user || user.bot) return false;
  try {
    await user.send({ embeds: [embed] });
    return true;
  } catch {
    return false;
  }
}

async function defer(interaction, ephemeral = true) {
  if (!interaction.deferred && !interaction.replied) await interaction.deferReply({ ephemeral });
}

async function reply(interaction, payload, ephemeral = true) {
  const body = typeof payload === 'string' ? { content: payload, ephemeral } : { ...payload, ephemeral: payload.ephemeral ?? ephemeral };
  if (Array.isArray(body.embeds)) {
    body.embeds = body.embeds.map((embed) => modernizeEmbed(embed, { author: interaction.user, guild: interaction.guild }));
    if (!body.components) {
      const rows = createButtonRows(defaultEmbedButtons({ guild: interaction.guild }));
      if (rows.length) body.components = rows;
    }
  }
  if (interaction.deferred || interaction.replied) return interaction.editReply(body);
  return interaction.reply(body);
}

module.exports = {
  utcnow,
  toAwareUtc,
  runWithEmbedContext,
  getEmbedContext,
  resolveAuthor,
  quoteDescription,
  modernizeEmbed,
  serverIconOf,
  serverBannerOf,
  createButtonRows,
  defaultEmbedButtons,
  embedPayload,
  createEmbed,
  successEmbed,
  errorEmbed,
  parseDuration,
  parseDurationMs,
  canModerate,
  formatDuration,
  checkPhishingUrl,
  generateCaptcha,
  safeDm,
  defer,
  reply,
};
