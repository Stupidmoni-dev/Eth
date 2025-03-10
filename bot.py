require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');
const Web3 = require('web3');
const { ethers } = require('ethers');
const sqlite3 = require('sqlite3').verbose();
const axios = require('axios');

// Load environment variables
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const INFURA_URL = process.env.INFURA_URL;
const CENTRAL_WALLET = process.env.CENTRAL_WALLET; // Admin ETH Wallet

// Initialize Web3 and Telegram Bot
const web3 = new Web3(new Web3.providers.HttpProvider(INFURA_URL));
const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });

// Setup SQLite Database
const db = new sqlite3.Database('./db_eth.sqlite', (err) => {
    if (err) console.error('Error opening database:', err);
    else console.log('Connected to SQLite database.');
});

// Create users table
db.run(`
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        eth_address TEXT NOT NULL,
        eth_private_key TEXT NOT NULL
    )
`);

// Function to create a new Ethereum wallet
function createWallet() {
    const wallet = ethers.Wallet.createRandom();
    return { address: wallet.address, privateKey: wallet.privateKey };
}

// Function to get ETH balance
async function getBalance(address) {
    const balanceWei = await web3.eth.getBalance(address);
    return web3.utils.fromWei(balanceWei, 'ether');
}

// Function to send ETH transaction
async function sendEthTransaction(privateKey, to, amount) {
    try {
        const wallet = new ethers.Wallet(privateKey, new ethers.providers.JsonRpcProvider(INFURA_URL));
        const tx = await wallet.sendTransaction({ to, value: ethers.utils.parseEther(amount.toString()) });
        return tx.hash;
    } catch (error) {
        console.error("Error sending transaction:", error);
        throw new Error("Transaction failed.");
    }
}

// Function to fetch contract details from Dexscreener
async function getDexscreenerContract(query) {
    try {
        const res = await axios.get(`https://api.dexscreener.com/latest/dex/search?q=${query}`);
        return res.data.pairs ? res.data.pairs[0] : null;
    } catch (error) {
        console.error("Error fetching contract:", error);
        return null;
    }
}

// /start - Create or retrieve wallet
bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id.toString();

    db.get(`SELECT * FROM users WHERE id = ?`, [chatId], async (err, row) => {
        if (err) console.error(err);
        else if (row) {
            bot.sendMessage(chatId, `💰 *Your ETH Wallet:* \n\`${row.eth_address}\``, { parse_mode: "Markdown" });
        } else {
            const { address, privateKey } = createWallet();
            db.run(`INSERT INTO users (id, eth_address, eth_private_key) VALUES (?, ?, ?)`, 
                [chatId, address, privateKey],
                (err) => {
                    if (err) console.error(err);
                    else bot.sendMessage(chatId, `✅ *New Wallet Created:* \n\`${address}\``, { parse_mode: "Markdown" });
                }
            );
        }
    });
});

// /balance - Check ETH balance
bot.onText(/\/balance/, async (msg) => {
    const chatId = msg.chat.id.toString();
    db.get(`SELECT * FROM users WHERE id = ?`, [chatId], async (err, row) => {
        if (err || !row) return bot.sendMessage(chatId, "⚠️ No wallet found! Use /start to create one.");
        const balance = await getBalance(row.eth_address);
        bot.sendMessage(chatId, `💰 *Your Balance:* ${balance} ETH`, { parse_mode: "Markdown" });
    });
});

// /trade - Fetch token contract
bot.onText(/\/trade (.+)/, async (msg, match) => {
    const chatId = msg.chat.id.toString();
    const query = match[1];

    const contractData = await getDexscreenerContract(query);
    if (!contractData) return bot.sendMessage(chatId, "⚠️ Contract not found!");

    const contractAddress = contractData.baseToken.address;
    bot.sendMessage(chatId, `📊 *Token:* ${contractData.baseToken.symbol}\n💲 *Price:* $${contractData.priceUsd}\n🔗 *Contract:* \`${contractAddress}\``, {
        parse_mode: "Markdown",
        reply_markup: {
            inline_keyboard: [
                [{ text: "💰 Buy 0.1 ETH", callback_data: `buy_0.1_${contractAddress}` }],
                [{ text: "💰 Buy 0.5 ETH", callback_data: `buy_0.5_${contractAddress}` }],
                [{ text: "❌ Cancel", callback_data: "cancel" }]
            ]
        }
    });
});

// Handle buy & withdraw actions
bot.on("callback_query", async (query) => {
    const chatId = query.message.chat.id.toString();
    const data = query.data;

    db.get(`SELECT * FROM users WHERE id = ?`, [chatId], async (err, row) => {
        if (err || !row) return bot.sendMessage(chatId, "⚠️ No wallet found! Use /start to create one.");
        
        if (data.startsWith("buy_")) {
            const [_, amount, contractAddress] = data.split("_");

            try {
                const txHash = await sendEthTransaction(row.eth_private_key, contractAddress, parseFloat(amount));
                bot.sendMessage(chatId, `✅ *Transaction Sent:* \`${txHash}\``, { parse_mode: "Markdown" });
            } catch (e) {
                bot.sendMessage(chatId, `❌ *Transaction Failed:* ${e.message}`);
            }
        }

        if (data === "withdraw") {
            bot.sendMessage(chatId, "🔹 Reply with your Ethereum address to withdraw.");
            bot.once("message", async (withdrawMsg) => {
                const toAddress = withdrawMsg.text.trim();
                if (!web3.utils.isAddress(toAddress)) return bot.sendMessage(chatId, "⚠️ Invalid Ethereum address!");
                
                try {
                    const balance = await getBalance(row.eth_address);
                    const txHash = await sendEthTransaction(row.eth_private_key, toAddress, balance);
                    bot.sendMessage(chatId, `✅ *Withdrawn!* TX: \`${txHash}\``, { parse_mode: "Markdown" });
                } catch (e) {
                    bot.sendMessage(chatId, `❌ *Withdrawal Failed:* ${e.message}`);
                }
            });
        }
    });
});

// /help - Display available commands
bot.onText(/\/help/, (msg) => {
    bot.sendMessage(msg.chat.id, `
    ℹ️ *Available Commands:*
    /start - Create or retrieve wallet
    /balance - Check ETH balance
    /trade <token> - Fetch contract & buy options
    /withdraw - Withdraw ETH to an external wallet
    /help - Show this help menu
    `, { parse_mode: "Markdown" });
});
