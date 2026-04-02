# Polymarket Auto-Redeem Bot - Setup Guide

## 📋 Overview

Bot อัตโนมัติสำหรับ redeem winning tokens จาก Polymarket โดยใช้ Relayer API (gasless)

---

## 🔑 Authentication Options

### วิธีที่ 1: Relayer API Keys (ง่าย - แนะนำสำหรับเริ่มต้น)

1. ไปที่ https://polymarket.com
2. Settings > API Keys
3. สร้าง Relayer API Key
4. เก็บ API Key และ Address ไว้

**ข้อดี:**
- ✅ สร้างได้ง่าย
- ✅ ไม่ต้องสมัคร Builder Program

**ข้อเสีย:**
- ❌ ฟีเจอร์จำกัด
- ❌ อาจมี rate limits

---

### วิธีที่ 2: Builder API Keys (แนะนำสำหรับ Production)

1. สมัคร Builder Program ที่ https://polymarket.com/builder
2. รอ approval จาก Polymarket team
3. ได้รับ credentials:
   - Builder API Key
   - Builder Secret
   - Builder Passphrase

**ข้อดี:**
- ✅ ฟีเจอร์ครบถ้วน
- ✅ Rate limits สูงกว่า
- ✅ Support ดีกว่า

**ข้อเสีย:**
- ❌ ต้องสมัครและรอ approval
- ❌ ต้องมี trading volume บางอย่าง

---

## ⚙️ การตั้งค่า

### 1. ติดตั้ง Dependencies

```bash
npm install
```

### 2. แก้ไข redeem-config.json

```json
{
  "relayerApiKey": "YOUR_RELAYER_API_KEY",
  "privateKey": "YOUR_PRIVATE_KEY",
  "conditionIds": [],
  "autoMode": true,
  "checkInterval": 300,
  "clobHost": "https://clob.polymarket.com",
  "chainId": 137,
  "signatureType": 2,
  "funder": "YOUR_SAFE_WALLET_ADDRESS",
  
  "builderApiKey": "YOUR_BUILDER_API_KEY",
  "builderSecret": "YOUR_BUILDER_SECRET",
  "builderPassphrase": "YOUR_BUILDER_PASSPHRASE"
}
```

### 3. ตั้งค่า Environment Variables (ทางเลือก)

```bash
export POLYMARKET_RELAYER_URL="https://relayer-v2.polymarket.com"
export POLY_BUILDER_API_KEY="your_key"
export POLY_BUILDER_SECRET="your_secret"
export POLY_BUILDER_PASSPHRASE="your_passphrase"
```

---

## 🚀 วิธีใช้งาน

### Auto Mode (แนะนำ)

Bot จะสแกนทุก 5 นาที และ redeem อัตโนมัติ:

```bash
npm run redeem
```

**Output:**
```
🤖 Polymarket Auto-Redeem Bot
🔄 Auto mode enabled (check every 300s)

🔍 Scanning for redeemable positions...
📊 Found 5 closed markets
   ✅ Ready to redeem: Bitcoin Up or Down...
   
🚀 Starting redemption...
   ✅ Success! TX: 0xabc123...
```

### Manual Mode

 redeem เฉพาะ condition IDs ที่ระบุ:

```json
{
  "autoMode": false,
  "conditionIds": [
    "0x1234...",
    "0x5678..."
  ]
}
```

```bash
npm run redeem
```

---

## 📁 ไฟล์ที่สำคัญ

| ไฟล์ | คำอธิบาย |
|------|----------|
| `redeem.ts` | Main bot script |
| `get-resolved.py` | Python helper สำหรับดึง positions |
| `redeem-config.json` | Config file |
| `claimed.json` | เก็บ condition IDs ที่ claim แล้ว (auto create) |

---

## 🔍 การแก้ปัญหา

### Error: 401 Unauthorized

**สาเหตุ:** ไม่มี Builder credentials หรือ credentials ไม่ถูกต้อง

**วิธีแก้:**
1. ตรวจสอบ builderApiKey, builderSecret, builderPassphrase ใน config
2. ตรวจสอบว่าสมัคร Builder Program แล้ว
3. ติดต่อ Polymarket support

### Error: 404 Not Found

**สาเหตุ:** Relayer URL ไม่ถูกต้อง

**วิธีแก้:**
```json
{
  "relayerUrl": "https://relayer-v2.polymarket.com"
}
```

### Error: No positions to redeem

**สาเหตุ:** ไม่มีตลาดที่ resolve แล้ว

**วิธีแก้:** รอให้ตลาด resolve ก่อน

---

## 📊 ตัวอย่าง Config

### สำหรับ Relayer API Keys (วิธีที่ 1)

```json
{
  "relayerApiKey": "your_relayer_key",
  "privateKey": "your_private_key",
  "autoMode": true,
  "checkInterval": 300
}
```

### สำหรับ Builder API Keys (วิธีที่ 2 - แนะนำ)

```json
{
  "relayerApiKey": "your_relayer_key",
  "privateKey": "your_private_key",
  "autoMode": true,
  "checkInterval": 300,
  "builderApiKey": "your_builder_key",
  "builderSecret": "your_builder_secret",
  "builderPassphrase": "your_builder_passphrase"
}
```

---

## 🔗 Links ที่สำคัญ

- [Polymarket Builder Program](https://polymarket.com/builder)
- [Polymarket Settings > API Keys](https://polymarket.com/settings/api-keys)
- [Relayer Documentation](https://docs.polymarket.com/trading/gasless)
- [Builder Relayer Client (GitHub)](https://github.com/Polymarket/builder-relayer-client-ts)

---

## 📞 ติดต่อ Support

- Polymarket Discord: https://discord.gg/polymarket
- Email: support@polymarket.com

---

## ⚠️ คำเตือน

1. **อย่าแชร์ private key หรือ Builder credentials**
2. **ใช้ environment variables สำหรับ production**
3. **ทดสอบด้วยจำนวนน้อยก่อน**
4. **ตรวจสอบ transaction ก่อน redeem จริง**
