import express from "express";
import type { Request, Response } from "express";
import { createClient } from "redis";

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const REDIS_URL = process.env.REDIS_URL || "redis://localhost:6379";

const redisClient = createClient({ url: REDIS_URL });
redisClient.on("error", (err: Error) => console.error("Redis error:", err));
await redisClient.connect();

function formatInAraguaina(date: Date): string {
  const dtf = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Araguaina",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  });
  return dtf.format(date);
}

app.get("/stream", async (req: Request, res: Response) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");

  console.log("Client connected to stream");

  const interval = setInterval(async () => {
    const temperature = (Math.random() * 100).toFixed(2);
    const timestamp = formatInAraguaina(new Date());
    const data = { temperature, timestamp };
    res.write(`data: ${JSON.stringify(data)}\n\n`);
    const key = "temperatures";
    await redisClient.rPush(key, JSON.stringify(data));
    await redisClient.lTrim(key, -86400, -1);
  }, 1000);

  req.on("close", () => {
    clearInterval(interval);
    console.log("Client disconnected from stream");
  });
});

app.get("/history", async (_req: Request, res: Response) => {
  const key = "temperatures";
  const values: string[] = await redisClient.lRange(key, 0, -1);
  const parsed = values.map((v: string) => JSON.parse(v));
  res.json(parsed);
});

app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
