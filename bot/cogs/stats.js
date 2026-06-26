const { SlashCommandBuilder } = require('discord.js');
const { createEmbed, reply } = require('../utils');
const { COLOR_PRIMARY, COLOR_SUCCESS } = require('../config');
const msgHeat=new Map();
const events=[{name:'messageCreate',async execute(bot,message){if(message.guild&&!message.author.bot){const key=`${message.guild.id}:${new Date().getHours()}`;msgHeat.set(key,(msgHeat.get(key)||0)+1);}}}];
const commands=[
{data:new SlashCommandBuilder().setName('stats').setDescription('Server-Statistiken anzeigen'),async execute(bot,i){return reply(i,{embeds:[createEmbed('📊 Server-Statistiken',`Member: **${i.guild.memberCount}**\nRollen: **${i.guild.roles.cache.size}**\nChannels: **${i.guild.channels.cache.size}**`,COLOR_PRIMARY)]},true);}},
{data:new SlashCommandBuilder().setName('heatmap').setDescription('Server-Aktivitäts-Heatmap'),async execute(bot,i){const rows=[...msgHeat.entries()].filter(([k])=>k.startsWith(i.guild.id+':')).map(([k,v])=>`${k.split(':')[1]} Uhr: ${v}`).join('\n')||'Noch keine Daten.';return reply(i,{embeds:[createEmbed('🔥 Aktivitäts-Heatmap',rows,COLOR_PRIMARY)]},true);}},
{data:new SlashCommandBuilder().setName('botstats').setDescription('Bot-Performance-Statistiken'),async execute(bot,i){return reply(i,{embeds:[createEmbed('🤖 Bot-Statistiken',`Ping: **${Math.round(bot.ws.ping)}ms**\nServer: **${bot.guilds.cache.size}**\nRAM: **${Math.round(process.memoryUsage().rss/1024/1024)} MB**`,COLOR_SUCCESS)]},true);}},
{data:new SlashCommandBuilder().setName('stats_enable').setDescription('Aktiviert das Stats-System'),async execute(bot,i){await bot.db.updateModule(i.guild.id,'stats','enabled',true);return reply(i,{embeds:[createEmbed('✅ Stats aktiviert','Stats-System wurde aktiviert.',COLOR_SUCCESS)]},true);}},
{data:new SlashCommandBuilder().setName('cmdstats').setDescription('Zeigt Command-Nutzungsstatistiken'),async execute(bot,i){return reply(i,{embeds:[createEmbed('📈 Command-Stats',`Registrierte Slash Commands: **${bot.commands.size}**`,COLOR_PRIMARY)]},true);}},
{data:new SlashCommandBuilder().setName('rolestats').setDescription('Zeigt Rollen-Verteilung'),async execute(bot,i){const text=i.guild.roles.cache.sort((a,b)=>b.members.size-a.members.size).first(10).map(r=>`${r}: ${r.members.size}`).join('\n');return reply(i,{embeds:[createEmbed('🏷️ Rollen-Verteilung',text||'Keine Daten.',COLOR_PRIMARY)]},true);}},
{data:new SlashCommandBuilder().setName('growth').setDescription('Server-Wachstum anzeigen'),async execute(bot,i){return reply(i,{embeds:[createEmbed('📈 Wachstum',`Aktuelle Member: **${i.guild.memberCount}**`,COLOR_PRIMARY)]},true);}},
];module.exports={commands,events};
