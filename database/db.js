// database/db.js – MongoDB Layer für ModForge Node.js Migration
const { MongoClient, ObjectId } = require('mongodb');
const { DEFAULT_CONFIG, devPrint } = require('../bot/config');

function deepClone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

function deepMerge(base, override) {
  const result = deepClone(base || {});
  for (const [key, value] of Object.entries(override || {})) {
    if (value && typeof value === 'object' && !Array.isArray(value) && result[key] && typeof result[key] === 'object' && !Array.isArray(result[key])) {
      result[key] = deepMerge(result[key], value);
    } else {
      result[key] = deepClone(value);
    }
  }
  return result;
}

function ensureDefaults(cfg) {
  const clean = deepClone(cfg || {});
  delete clean._id;
  return deepMerge(DEFAULT_CONFIG, clean);
}

class TTLMap {
  constructor(ttlMs = 300000, maxSize = 10000) {
    this.ttlMs = ttlMs;
    this.maxSize = maxSize;
    this.map = new Map();
  }
  get(key) {
    const hit = this.map.get(String(key));
    if (!hit) return null;
    if (Date.now() - hit.ts > this.ttlMs) {
      this.map.delete(String(key));
      return null;
    }
    return hit.value;
  }
  set(key, value) {
    if (this.map.size > this.maxSize) this.map.delete(this.map.keys().next().value);
    this.map.set(String(key), { value, ts: Date.now() });
  }
  delete(key) { this.map.delete(String(key)); }
}

class Database {
  constructor(mongoUrl = null) {
    this.mongoUrl = process.env.MONGO_URL || mongoUrl || 'mongodb://localhost:27017';
    this.client = new MongoClient(this.mongoUrl, { serverSelectionTimeoutMS: 8000, tlsAllowInvalidCertificates: true });
    this.ready = false;
    this.configCache = new TTLMap(300000, 10000);
    this.whitelistCache = new TTLMap(300000, 10000);
  }

  async connect() {
    if (this.ready) return this;
    await this.client.connect();
    this.db = this.client.db('ModForge');
    this.config = this.db.collection('config');
    this.whitelist = this.db.collection('whitelist');
    this.data = this.db.collection('data');
    this.tempactions = this.db.collection('tempactions');
    this.cases = this.db.collection('cases');
    this.counters = this.db.collection('counters');
    this.message_archive = this.db.collection('message_archive');
    this.guild_events = this.db.collection('guild_events');
    this.server_accounts = this.db.collection('server_accounts');
    this.tempvoice_channels = this.db.collection('tempvoice_channels');
    this.tempvoice_settings = this.db.collection('tempvoice_settings');
    this.tempvoice_ratings = this.db.collection('tempvoice_ratings');
    this.log_channels_backup = this.db.collection('log_channels_backup');
    this.notes = this.db.collection('notes');
    this.badges = this.db.collection('badges');
    this.badge_defs = this.db.collection('badge_defs');
    this.role_health = this.db.collection('role_health');
    this.ticket_transcripts = this.db.collection('ticket_transcripts');
    this.tempvoice_live = this.db.collection('tempvoice_live');
    this.livefeed_events = this.db.collection('livefeed_events');
    this.config_versions = this.db.collection('config_versions');
    this.ticket_panels = this.db.collection('ticket_panels');
    this.tempvoice_panels = this.db.collection('tempvoice_panels');
    this.appeals = this.db.collection('appeals');
    this.staff_applications = this.db.collection('staff_applications');
    this.server_themes = this.db.collection('server_themes');
    this.ready = true;
    await this.ensureIndexes();
    return this;
  }

  async testConnection() {
    try {
      await this.connect();
      await this.client.db('admin').command({ ping: 1 });
      devPrint('MongoDB-Verbindung erfolgreich getestet.', 'success', 'DB');
      return true;
    } catch (error) {
      devPrint(`MongoDB-Verbindungstest fehlgeschlagen: ${error.message}`, 'error', 'DB');
      return false;
    }
  }

  async ensureIndexes() {
    if (!this.ready) return;
    await Promise.allSettled([
      this.config.createIndex({ _id: 1 }, { unique: true }),
      this.whitelist.createIndex({ _id: 1 }, { unique: true }),
      this.cases.createIndex({ guild_id: 1, case_id: -1 }),
      this.data.createIndex({ guild_id: 1, type: 1 }),
      this.tempactions.createIndex({ expires_at: 1 }),
      this.notes.createIndex({ guild_id: 1, user_id: 1 }),
      this.badges.createIndex({ guild_id: 1, user_id: 1 }),
      this.config_versions.createIndex({ guild_id: 1, created_at: -1 }),
    ]);
  }

  getConfig(guildId) {
    const cached = this.configCache.get(guildId);
    if (cached) return cached;
    const fallback = ensureDefaults({});
    this.configCache.set(guildId, fallback);
    if (this.ready) this.fetchConfig(guildId).catch(() => null);
    return fallback;
  }

  async fetchConfig(guildId) {
    await this.connect();
    const gid = Number(guildId);
    let data = await this.config.findOne({ _id: gid });
    if (!data) {
      data = ensureDefaults({});
      await this.config.updateOne({ _id: gid }, { $setOnInsert: { ...deepClone(data), _id: gid } }, { upsert: true });
    }
    const cleaned = ensureDefaults(data);
    this.configCache.set(gid, cleaned);
    return cleaned;
  }

  async setConfig(guildId, cfg) {
    await this.connect();
    const gid = Number(guildId);
    const cleaned = ensureDefaults(cfg);
    await this.config.updateOne({ _id: gid }, { $set: deepClone(cleaned), $setOnInsert: { _id: gid } }, { upsert: true });
    this.configCache.set(gid, cleaned);
  }

  async updateModule(guildId, module, key, value) {
    const cfg = await this.fetchConfig(guildId);
    if (!cfg[module] || typeof cfg[module] !== 'object') cfg[module] = {};
    cfg[module][key] = value;
    await this.setConfig(guildId, cfg);
  }

  emptyWhitelist() {
    return { users: [], roles: [], channels: [], bypass_antispam: [], bypass_antinuke: [] };
  }

  getWhitelist(guildId) {
    const cached = this.whitelistCache.get(guildId);
    if (cached) return cached;
    const empty = this.emptyWhitelist();
    this.whitelistCache.set(guildId, empty);
    if (this.ready) this.fetchWhitelist(guildId).catch(() => null);
    return empty;
  }

  async fetchWhitelist(guildId) {
    await this.connect();
    const gid = Number(guildId);
    const data = await this.whitelist.findOne({ _id: gid }) || this.emptyWhitelist();
    delete data._id;
    for (const key of Object.keys(this.emptyWhitelist())) if (!Array.isArray(data[key])) data[key] = [];
    this.whitelistCache.set(gid, data);
    return data;
  }

  async setWhitelist(guildId, whitelist) {
    await this.connect();
    const gid = Number(guildId);
    const clean = { ...this.emptyWhitelist(), ...(whitelist || {}) };
    delete clean._id;
    await this.whitelist.updateOne({ _id: gid }, { $set: clean, $setOnInsert: { _id: gid } }, { upsert: true });
    this.whitelistCache.set(gid, clean);
  }

  async nextCaseId(guildId) {
    await this.connect();
    const doc = await this.counters.findOneAndUpdate(
      { _id: `case:${guildId}` },
      { $inc: { seq: 1 } },
      { upsert: true, returnDocument: 'after' }
    );
    return doc.seq || doc.value?.seq || 1;
  }

  async createCase(guildId, payload) {
    await this.connect();
    const caseId = payload.case_id || await this.nextCaseId(guildId);
    const doc = { ...payload, guild_id: Number(guildId), case_id: caseId, created_at: payload.created_at || new Date() };
    await this.cases.insertOne(doc);
    return doc;
  }

  async getCase(guildId, caseId) {
    await this.connect();
    return this.cases.findOne({ guild_id: Number(guildId), case_id: Number(caseId) });
  }

  async getCases(guildId, filter = {}, limit = 20) {
    await this.connect();
    return this.cases.find({ guild_id: Number(guildId), ...filter }).sort({ case_id: -1 }).limit(Number(limit) || 20).toArray();
  }

  async updateCase(guildId, caseId, patch) {
    await this.connect();
    return this.cases.updateOne({ guild_id: Number(guildId), case_id: Number(caseId) }, { $set: patch });
  }

  async saveData(doc) {
    await this.connect();
    return this.data.insertOne({ ...doc, created_at: doc.created_at || new Date() });
  }

  async getServerTheme(guildId) {
    await this.connect();
    return this.server_themes.findOne({ guild_id: Number(guildId) });
  }

  async setServerTheme(guildId, theme) {
    await this.connect();
    return this.server_themes.updateOne({ guild_id: Number(guildId) }, { $set: { guild_id: Number(guildId), theme, updated_at: new Date() } }, { upsert: true });
  }

  async getAllAppeals(guildId, limit = 50) {
    await this.connect();
    return this.appeals.find({ guild_id: Number(guildId) }).sort({ created_at: -1 }).limit(limit).toArray();
  }

  async updateAppealStatus(appealId, status, reviewerId = null) {
    await this.connect();
    const query = ObjectId.isValid(String(appealId)) ? { _id: new ObjectId(String(appealId)) } : { appeal_id: String(appealId) };
    return this.appeals.updateOne(query, { $set: { status, reviewer_id: reviewerId, reviewed_at: new Date() } });
  }

  async getAllStaffApplications(guildId, limit = 50) {
    await this.connect();
    return this.staff_applications.find({ guild_id: Number(guildId) }).sort({ created_at: -1 }).limit(limit).toArray();
  }



  // Python-Name-Aliase, damit alte Aufrufer dieselben Funktionsnamen behalten.
  async test_connection() { return this.testConnection(); }
  get_config(guildId) { return this.getConfig(guildId); }
  async fetch_config(guildId) { return this.fetchConfig(guildId); }
  async set_config(guildId, cfg) { return this.setConfig(guildId, cfg); }
  async update_module(guildId, module, key, value) { return this.updateModule(guildId, module, key, value); }
  get_whitelist(guildId) { return this.getWhitelist(guildId); }
  async fetch_whitelist(guildId) { return this.fetchWhitelist(guildId); }
  async set_whitelist(guildId, whitelist) { return this.setWhitelist(guildId, whitelist); }
  async ensure_indexes() { return this.ensureIndexes(); }

  // ── 1:1-Kompatibilitätsmethoden aus database/db.py ─────────────────────
  async aget_config(guildId) { return this.fetchConfig(guildId); }
  async aset_config(guildId, cfg) { return this.setConfig(guildId, cfg); }
  async aupdate_module(guildId, module, key, value) { return this.updateModule(guildId, module, key, value); }
  async aget_whitelist(guildId) { return this.fetchWhitelist(guildId); }

  async addWhitelist(guildId, kind, id) { return this.add_whitelist(guildId, kind, id); }
  async add_whitelist(guildId, kind, id) {
    const wl = await this.fetchWhitelist(guildId);
    if (!Array.isArray(wl[kind])) wl[kind] = [];
    const value = String(id);
    if (!wl[kind].map(String).includes(value)) wl[kind].push(value);
    await this.setWhitelist(guildId, wl);
    return wl;
  }
  async removeWhitelist(guildId, kind, id) { return this.remove_whitelist(guildId, kind, id); }
  async remove_whitelist(guildId, kind, id) {
    const wl = await this.fetchWhitelist(guildId);
    if (!Array.isArray(wl[kind])) wl[kind] = [];
    wl[kind] = wl[kind].filter((x) => String(x) !== String(id));
    await this.setWhitelist(guildId, wl);
    return wl;
  }
  async aadd_whitelist(guildId, kind, id) { return this.add_whitelist(guildId, kind, id); }
  async aremove_whitelist(guildId, kind, id) { return this.remove_whitelist(guildId, kind, id); }

  async aadd_warning(guildId, userId, moderatorId, reason = 'Kein Grund') {
    await this.connect();
    const doc = { type: 'warning', guild_id: Number(guildId), user_id: String(userId), moderator_id: String(moderatorId), reason, active: true, created_at: new Date() };
    await this.data.insertOne(doc);
    return doc;
  }
  async aget_warnings(guildId, userId) { await this.connect(); return this.data.find({ type: 'warning', guild_id: Number(guildId), user_id: String(userId), active: { $ne: false } }).sort({ created_at: -1 }).toArray(); }
  async aclear_warnings(guildId, userId) { await this.connect(); return this.data.updateMany({ type: 'warning', guild_id: Number(guildId), user_id: String(userId) }, { $set: { active: false, cleared_at: new Date() } }); }
  async aremove_warning(guildId, warningId) { await this.connect(); const q = ObjectId.isValid(String(warningId)) ? { _id: new ObjectId(String(warningId)) } : { guild_id: Number(guildId), warning_id: warningId }; return this.data.updateOne(q, { $set: { active: false, removed_at: new Date() } }); }

  async aadd_mute(guildId, userId, moderatorId, reason, until) { await this.connect(); const doc = { type: 'mute', guild_id: Number(guildId), user_id: String(userId), moderator_id: String(moderatorId), reason, until, active: true, created_at: new Date() }; await this.tempactions.insertOne(doc); return doc; }
  async aget_active_mutes() { await this.connect(); return this.tempactions.find({ type: 'mute', active: true }).toArray(); }
  async adeactivate_mute(guildId, userId) { await this.connect(); return this.tempactions.updateMany({ type: 'mute', guild_id: Number(guildId), user_id: String(userId), active: true }, { $set: { active: false, deactivated_at: new Date() } }); }

  async aadd_temp_voice(guildId, channelId, ownerId) { await this.connect(); const doc = { guild_id: Number(guildId), channel_id: String(channelId), owner_id: String(ownerId), created_at: new Date() }; await this.tempvoice_channels.updateOne({ guild_id: Number(guildId), channel_id: String(channelId) }, { $set: doc }, { upsert: true }); return doc; }
  async aget_temp_voice(channelId) { await this.connect(); return this.tempvoice_channels.findOne({ channel_id: String(channelId) }); }
  async aremove_temp_voice(channelId) { await this.connect(); return this.tempvoice_channels.deleteOne({ channel_id: String(channelId) }); }
  async aupdate_temp_voice_owner(channelId, ownerId) { await this.connect(); return this.tempvoice_channels.updateOne({ channel_id: String(channelId) }, { $set: { owner_id: String(ownerId), updated_at: new Date() } }); }

  async aadd_tempaction(guildId, action, userId, data = {}, expiresAt = null) { await this.connect(); const doc = { guild_id: Number(guildId), action, user_id: String(userId), data, expires_at: expiresAt, active: true, created_at: new Date() }; await this.tempactions.insertOne(doc); return doc; }
  async aget_due_tempactions(now = new Date()) { await this.connect(); return this.tempactions.find({ active: true, expires_at: { $lte: now } }).toArray(); }
  async adeactivate_tempaction(id) { await this.connect(); const q = ObjectId.isValid(String(id)) ? { _id: new ObjectId(String(id)) } : { id }; return this.tempactions.updateOne(q, { $set: { active: false, deactivated_at: new Date() } }); }

  _normalize_badge_id(id) { return String(id || '').toLowerCase().trim().replace(/[^a-z0-9_\-]/g, '_'); }
  async badge_definitions(guildId) { await this.connect(); return this.badge_defs.find({ $or: [{ guild_id: Number(guildId) }, { global: true }] }).toArray(); }
  async badge_def_upsert(guildId, badgeId, data) { await this.connect(); const id = this._normalize_badge_id(badgeId); await this.badge_defs.updateOne({ guild_id: Number(guildId), badge_id: id }, { $set: { ...data, guild_id: Number(guildId), badge_id: id, updated_at: new Date() } }, { upsert: true }); return id; }
  async badge_def_delete(guildId, badgeId) { await this.connect(); return this.badge_defs.deleteOne({ guild_id: Number(guildId), badge_id: this._normalize_badge_id(badgeId) }); }
  async badge_event(guildId, userId, badgeId, action, actorId = null) { await this.connect(); return this.data.insertOne({ type: 'badge_event', guild_id: Number(guildId), user_id: String(userId), badge_id: this._normalize_badge_id(badgeId), action, actor_id: actorId ? String(actorId) : null, created_at: new Date() }); }
  async badge_history(guildId, userId, limit = 50) { await this.connect(); return this.data.find({ type: 'badge_event', guild_id: Number(guildId), user_id: String(userId) }).sort({ created_at: -1 }).limit(limit).toArray(); }
  async badge_add(guildId, userId, badgeId, actorId = null) { await this.connect(); const id = this._normalize_badge_id(badgeId); await this.badges.updateOne({ guild_id: Number(guildId), user_id: String(userId) }, { $addToSet: { badges: id }, $set: { updated_at: new Date() } }, { upsert: true }); await this.badge_event(guildId, userId, id, 'add', actorId); }
  async badge_remove(guildId, userId, badgeId, actorId = null) { await this.connect(); const id = this._normalize_badge_id(badgeId); await this.badges.updateOne({ guild_id: Number(guildId), user_id: String(userId) }, { $pull: { badges: id }, $set: { updated_at: new Date() } }); await this.badge_event(guildId, userId, id, 'remove', actorId); }
  async badge_get_all(guildId, userId) { await this.connect(); const doc = await this.badges.findOne({ guild_id: Number(guildId), user_id: String(userId) }); return doc?.badges || []; }
  async badge_reorder(guildId, userId, order) { await this.connect(); return this.badges.updateOne({ guild_id: Number(guildId), user_id: String(userId) }, { $set: { badges: order.map((x) => this._normalize_badge_id(x)), updated_at: new Date() } }, { upsert: true }); }
  async badge_get_details(guildId, userId) { return { badges: await this.badge_get_all(guildId, userId), definitions: await this.badge_definitions(guildId) }; }
  async badge_get_all_guild(guildId) { await this.connect(); return this.badges.find({ guild_id: Number(guildId) }).toArray(); }
  async badge_get_all_guild_details(guildId) { return { users: await this.badge_get_all_guild(guildId), definitions: await this.badge_definitions(guildId) }; }

  async add_note(guildId, userId, moderatorId, text) { await this.connect(); const doc = { guild_id: Number(guildId), user_id: String(userId), moderator_id: String(moderatorId), text, created_at: new Date() }; await this.notes.insertOne(doc); return doc; }
  async get_notes(guildId, userId, limit = 20) { await this.connect(); return this.notes.find({ guild_id: Number(guildId), user_id: String(userId) }).sort({ created_at: -1 }).limit(limit).toArray(); }
  async delete_note(guildId, noteId) { await this.connect(); const q = ObjectId.isValid(String(noteId)) ? { _id: new ObjectId(String(noteId)), guild_id: Number(guildId) } : { guild_id: Number(guildId), note_id: noteId }; return this.notes.deleteOne(q); }

  async tv_get_channel(channelId) { return this.aget_temp_voice(channelId); }
  async tv_set_channel(guildId, channelId, ownerId, data = {}) { await this.connect(); return this.tempvoice_channels.updateOne({ guild_id: Number(guildId), channel_id: String(channelId) }, { $set: { ...data, guild_id: Number(guildId), channel_id: String(channelId), owner_id: String(ownerId), updated_at: new Date() } }, { upsert: true }); }
  async tv_del_channel(channelId) { return this.aremove_temp_voice(channelId); }
  async tv_get_all_channels(guildId) { await this.connect(); return this.tempvoice_channels.find({ guild_id: Number(guildId) }).toArray(); }
  async tv_get_settings(guildId) { await this.connect(); return await this.tempvoice_settings.findOne({ guild_id: Number(guildId) }) || {}; }
  async tv_save_settings(guildId, settings) { await this.connect(); return this.tempvoice_settings.updateOne({ guild_id: Number(guildId) }, { $set: { ...settings, guild_id: Number(guildId), updated_at: new Date() } }, { upsert: true }); }
  async tv_save_rating(guildId, channelId, userId, rating) { await this.connect(); return this.tempvoice_ratings.insertOne({ guild_id: Number(guildId), channel_id: String(channelId), user_id: String(userId), rating, created_at: new Date() }); }
  async tv_get_rating_cd(guildId, userId) { await this.connect(); return this.tempvoice_ratings.findOne({ guild_id: Number(guildId), user_id: String(userId) }, { sort: { created_at: -1 } }); }
  async tv_get_stats(guildId) { await this.connect(); return { channels: await this.tempvoice_channels.countDocuments({ guild_id: Number(guildId) }), ratings: await this.tempvoice_ratings.countDocuments({ guild_id: Number(guildId) }) }; }

  async log_channels_snapshot(guildId, channels) { await this.connect(); return this.log_channels_backup.updateOne({ guild_id: Number(guildId) }, { $set: { guild_id: Number(guildId), channels, updated_at: new Date() } }, { upsert: true }); }
  async log_channels_restore(guildId) { await this.connect(); const doc = await this.log_channels_backup.findOne({ guild_id: Number(guildId) }); return doc?.channels || {}; }

  async anext_case_id(guildId) { return this.nextCaseId(guildId); }
  async acreate_case(guildId, userIdOrPayload, modId = null, action = null, reason = 'Kein Grund', duration = null) {
    if (typeof userIdOrPayload === 'object' && userIdOrPayload !== null) return this.createCase(guildId, userIdOrPayload);
    return this.createCase(guildId, {
      user_id: String(userIdOrPayload),
      moderator_id: modId ? String(modId) : null,
      action,
      reason,
      duration,
    });
  }
  async aget_case(guildId, caseId) { return this.getCase(guildId, caseId); }
  async aget_recent_cases(guildId, limit = 20) { return this.getCases(guildId, {}, limit); }
  async aupdate_case_reason(guildId, caseId, reason, modId = null) {
    const res = await this.updateCase(guildId, caseId, { reason, edited_by: modId ? String(modId) : null, edited_at: new Date() });
    return Boolean(res.matchedCount || res.modifiedCount);
  }
  async aadd_case_evidence(guildId, caseId, evidence) { await this.connect(); return this.cases.updateOne({ guild_id: Number(guildId), case_id: Number(caseId) }, { $push: { evidence }, $set: { updated_at: new Date() } }); }
  async aattach_messages_to_case(guildId, caseId, messages) { await this.connect(); return this.cases.updateOne({ guild_id: Number(guildId), case_id: Number(caseId) }, { $push: { messages: { $each: messages } } }); }

  async arecord_message(guildId, message) { await this.connect(); const doc = { guild_id: Number(guildId), message_id: String(message.id), channel_id: String(message.channelId || message.channel?.id), user_id: String(message.author?.id || message.user_id || ''), content: message.content || '', created_at: new Date(message.createdTimestamp || Date.now()), deleted: false }; await this.message_archive.updateOne({ guild_id: Number(guildId), message_id: doc.message_id }, { $set: doc }, { upsert: true }); return doc; }
  async amark_message_deleted(guildId, messageId) { await this.connect(); return this.message_archive.updateOne({ guild_id: Number(guildId), message_id: String(messageId) }, { $set: { deleted: true, deleted_at: new Date() } }); }
  async aappend_message_edit(guildId, messageId, before, after) { await this.connect(); return this.message_archive.updateOne({ guild_id: Number(guildId), message_id: String(messageId) }, { $push: { edits: { before, after, edited_at: new Date() } } }, { upsert: true }); }
  async aget_user_messages(guildId, userId, limit = 50) { await this.connect(); return this.message_archive.find({ guild_id: Number(guildId), user_id: String(userId) }).sort({ created_at: -1 }).limit(limit).toArray(); }

  async arecord_guild_event(guildId, type, data = {}) { await this.connect(); const doc = { guild_id: Number(guildId), type, data, created_at: new Date() }; await this.guild_events.insertOne(doc); return doc; }
  async aget_recent_guild_events(guildId, limit = 50) { await this.connect(); return this.guild_events.find({ guild_id: Number(guildId) }).sort({ created_at: -1 }).limit(limit).toArray(); }
  async asave_role_health(guildId, data) { await this.connect(); return this.role_health.updateOne({ guild_id: Number(guildId) }, { $set: { guild_id: Number(guildId), data, updated_at: new Date() } }, { upsert: true }); }
  async aget_role_health(guildId) { await this.connect(); return this.role_health.findOne({ guild_id: Number(guildId) }); }
  async aget_all_role_health() { await this.connect(); return this.role_health.find({}).toArray(); }

  async asave_ticket_transcript(guildId, ticketId, data) { await this.connect(); return this.ticket_transcripts.updateOne({ guild_id: Number(guildId), ticket_id: String(ticketId) }, { $set: { ...data, guild_id: Number(guildId), ticket_id: String(ticketId), updated_at: new Date() } }, { upsert: true }); }
  async aget_ticket_transcripts(guildId, limit = 50) { await this.connect(); return this.ticket_transcripts.find({ guild_id: Number(guildId) }).sort({ updated_at: -1 }).limit(limit).toArray(); }
  async asearch_ticket_transcripts(guildId, query, limit = 50) { await this.connect(); return this.ticket_transcripts.find({ guild_id: Number(guildId), $text: { $search: query } }).limit(limit).toArray().catch(() => this.ticket_transcripts.find({ guild_id: Number(guildId) }).limit(limit).toArray()); }

  async atv_set_live_channel(guildId, channelId, data = {}) { await this.connect(); return this.tempvoice_live.updateOne({ guild_id: Number(guildId), channel_id: String(channelId) }, { $set: { ...data, guild_id: Number(guildId), channel_id: String(channelId), updated_at: new Date() } }, { upsert: true }); }
  async atv_remove_live_channel(guildId, channelId) { await this.connect(); return this.tempvoice_live.deleteOne({ guild_id: Number(guildId), channel_id: String(channelId) }); }
  async atv_get_live_channels(guildId) { await this.connect(); return this.tempvoice_live.find({ guild_id: Number(guildId) }).toArray(); }
  async arecord_livefeed_event(guildId, type, data = {}) { await this.connect(); return this.livefeed_events.insertOne({ guild_id: Number(guildId), type, data, created_at: new Date() }); }
  async aget_livefeed_events(guildId, limit = 50) { await this.connect(); return this.livefeed_events.find({ guild_id: Number(guildId) }).sort({ created_at: -1 }).limit(limit).toArray(); }

  async asave_config_version(guildId, cfg, source = 'bot') { await this.connect(); return this.config_versions.insertOne({ guild_id: Number(guildId), config: deepClone(cfg), source, created_at: new Date() }); }
  async aget_config_versions(guildId, limit = 25) { await this.connect(); return this.config_versions.find({ guild_id: Number(guildId) }).sort({ created_at: -1 }).limit(limit).toArray(); }
  async aget_config_version(id) { await this.connect(); const q = ObjectId.isValid(String(id)) ? { _id: new ObjectId(String(id)) } : { version_id: id }; return this.config_versions.findOne(q); }
  async asave_ticket_panel(guildId, data) { await this.connect(); return this.ticket_panels.updateOne({ guild_id: Number(guildId) }, { $set: { ...data, guild_id: Number(guildId), updated_at: new Date() } }, { upsert: true }); }
  async aget_ticket_panel(guildId) { await this.connect(); return this.ticket_panels.findOne({ guild_id: Number(guildId) }); }
  async asave_tempvoice_panel(guildId, data) { await this.connect(); return this.tempvoice_panels.updateOne({ guild_id: Number(guildId) }, { $set: { ...data, guild_id: Number(guildId), updated_at: new Date() } }, { upsert: true }); }
  async aget_tempvoice_panel(guildId) { await this.connect(); return this.tempvoice_panels.findOne({ guild_id: Number(guildId) }); }
  async arecord_activity(guildId, type, message, data = {}) { await this.connect(); return this.data.insertOne({ type: 'activity', guild_id: Number(guildId), activity_type: type, message, data, created_at: new Date() }); }
  async aget_activity_feed(guildId, limit = 50) { await this.connect(); return this.data.find({ type: 'activity', guild_id: Number(guildId) }).sort({ created_at: -1 }).limit(limit).toArray(); }
  async aget_user_risk(guildId, userId) { await this.connect(); return this.server_accounts.findOne({ guild_id: Number(guildId), user_id: String(userId) }) || { guild_id: Number(guildId), user_id: String(userId), risk_score: 0, flags: [] }; }
  async aupdate_user_risk(guildId, userId, patch) { await this.connect(); return this.server_accounts.updateOne({ guild_id: Number(guildId), user_id: String(userId) }, { $set: { ...patch, guild_id: Number(guildId), user_id: String(userId), updated_at: new Date() } }, { upsert: true }); }

  async acreate_appeal(guildId, userId, reason) { await this.connect(); const doc = { guild_id: Number(guildId), user_id: String(userId), reason, status: 'pending', created_at: new Date() }; await this.appeals.insertOne(doc); return doc; }
  async aget_pending_appeals(guildId, limit = 50) { await this.connect(); return this.appeals.find({ guild_id: Number(guildId), status: 'pending' }).sort({ created_at: -1 }).limit(limit).toArray(); }
  async acreate_staff_application(guildId, userId, question) { await this.connect(); const doc = { guild_id: Number(guildId), user_id: String(userId), question, status: 'pending', created_at: new Date() }; await this.staff_applications.insertOne(doc); return doc; }
  async aget_pending_applications(guildId, limit = 50) { await this.connect(); return this.staff_applications.find({ guild_id: Number(guildId), status: 'pending' }).sort({ created_at: -1 }).limit(limit).toArray(); }
  async asave_server_theme(guildId, theme) { return this.setServerTheme(guildId, theme); }
  async aget_server_theme(guildId) { return this.getServerTheme(guildId); }
  async aget_all_appeals(guildId, limit = 50) { return this.getAllAppeals(guildId, limit); }
  async aget_appeal_by_id(appealId) { await this.connect(); const q = ObjectId.isValid(String(appealId)) ? { _id: new ObjectId(String(appealId)) } : { appeal_id: String(appealId) }; return this.appeals.findOne(q); }
  async aupdate_appeal_status(appealId, status, reviewerId = null) { return this.updateAppealStatus(appealId, status, reviewerId); }
  async adelete_appeal(appealId) { await this.connect(); const q = ObjectId.isValid(String(appealId)) ? { _id: new ObjectId(String(appealId)) } : { appeal_id: String(appealId) }; return this.appeals.deleteOne(q); }
  async acount_appeals(guildId, status = null) { await this.connect(); const q = { guild_id: Number(guildId) }; if (status) q.status = status; return this.appeals.countDocuments(q); }
  async aget_all_staff_applications(guildId, limit = 50) { return this.getAllStaffApplications(guildId, limit); }
  async aget_staff_application_by_id(appId) { await this.connect(); const q = ObjectId.isValid(String(appId)) ? { _id: new ObjectId(String(appId)) } : { app_id: String(appId) }; return this.staff_applications.findOne(q); }
  async aupdate_staff_application_status(appId, status, reviewerId = null, notes = '') { await this.connect(); const q = ObjectId.isValid(String(appId)) ? { _id: new ObjectId(String(appId)) } : { app_id: String(appId) }; return this.staff_applications.updateOne(q, { $set: { status, reviewer_id: reviewerId, notes, reviewed_at: new Date() } }); }
  async adelete_staff_application(appId) { await this.connect(); const q = ObjectId.isValid(String(appId)) ? { _id: new ObjectId(String(appId)) } : { app_id: String(appId) }; return this.staff_applications.deleteOne(q); }
  async acount_staff_applications(guildId, status = null) { await this.connect(); const q = { guild_id: Number(guildId) }; if (status) q.status = status; return this.staff_applications.countDocuments(q); }
  async acount_server_themes(guildId) { await this.connect(); return this.server_themes.countDocuments({ guild_id: Number(guildId) }); }

  async close() {
    await this.client.close();
    this.ready = false;
  }
}

module.exports = { Database, ensureDefaults, deepMerge, deepClone };
