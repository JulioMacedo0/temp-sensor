FROM node:20-alpine

WORKDIR /usr/src/app

COPY package.json pnpm-lock.yaml* ./

RUN npm install -g pnpm@8
RUN pnpm install --frozen-lockfile || pnpm install

COPY . .

RUN pnpm build

EXPOSE 3000

CMD ["node", "dist/app.js"]
