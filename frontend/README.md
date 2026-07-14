# Frontend

Vue 3、Pinia 和 Naive UI 单页工作台。产品交互范围见
[产品范围](../docs/PRODUCT.md)。

## 启动

```bash
npm install
npm run dev
```

开发服务器默认将 `/api` 代理到 `http://localhost:8000`。
端口被占用时可以通过 `VITE_API_PROXY_TARGET` 指向其他本地后端地址。

## 构建

```bash
npm run build
```

页面组件按项目导航、商品资料输入和 Agent 决策结果划分。
