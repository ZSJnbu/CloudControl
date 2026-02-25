/**
 * NIO 风格的 WebSocket 客户端
 * 参考 Java NIO 设计：Channel + Buffer + Selector
 *
 * 特点：
 * 1. 单一 WebSocket 连接处理所有通信
 * 2. 事件驱动，异步非阻塞
 * 3. 自动重连和心跳
 * 4. 消息队列和批处理
 */

class NIOChannel {
    constructor(udid, options = {}) {
        this.udid = udid;
        this.options = Object.assign({
            reconnectInterval: 2000,
            maxReconnectAttempts: 10,
            heartbeatInterval: 25000,
            messageQueueSize: 100
        }, options);

        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;

        // 事件处理器 - 类似 Selector
        this.handlers = new Map();

        // 消息缓冲区 - 类似 Buffer
        this.messageQueue = [];
        this.pendingRequests = new Map();

        // 状态
        this.subscriptions = new Set();

        // 心跳
        this.heartbeatTimer = null;
    }

    /**
     * 连接到服务器
     */
    connect() {
        return new Promise((resolve, reject) => {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            const url = `${protocol}//${location.host}/nio/${this.udid}/ws`;

            console.log('[NIO] 正在连接:', url);

            this.ws = new WebSocket(url);

            this.ws.onopen = () => {
                console.log('[NIO] 连接成功');
                this.connected = true;
                this.reconnectAttempts = 0;
                this._startHeartbeat();
                this._flushQueue();
                this._emit('connected');
                resolve();
            };

            this.ws.onclose = (event) => {
                console.log('[NIO] 连接关闭:', event.code, event.reason);
                this.connected = false;
                this._stopHeartbeat();
                this._emit('disconnected');
                this._tryReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('[NIO] 连接错误:', error);
                this._emit('error', error);
                if (!this.connected) {
                    reject(error);
                }
            };

            this.ws.onmessage = (event) => {
                this._handleMessage(event.data);
            };
        });
    }

    /**
     * 断开连接
     */
    disconnect() {
        this.reconnectAttempts = this.options.maxReconnectAttempts; // 阻止重连
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this._stopHeartbeat();
        this.connected = false;
    }

    /**
     * 发送消息
     */
    send(type, data = {}) {
        const message = {
            type: type,
            data: data,
            id: Date.now().toString(36) + Math.random().toString(36).substr(2, 5)
        };

        if (this.connected && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            // 加入队列等待发送
            if (this.messageQueue.length < this.options.messageQueueSize) {
                this.messageQueue.push(message);
            }
        }

        return message.id;
    }

    /**
     * 发送请求并等待响应
     */
    request(type, data = {}, timeout = 5000) {
        return new Promise((resolve, reject) => {
            const id = this.send(type, data);

            const timer = setTimeout(() => {
                this.pendingRequests.delete(id);
                reject(new Error('Request timeout'));
            }, timeout);

            this.pendingRequests.set(id, { resolve, reject, timer });
        });
    }

    /**
     * 订阅事件流
     */
    subscribe(target, options = {}) {
        this.subscriptions.add(target);
        return this.send('subscribe', { target, ...options });
    }

    /**
     * 取消订阅
     */
    unsubscribe(target) {
        this.subscriptions.delete(target);
        return this.send('unsubscribe', { target });
    }

    /**
     * 注册事件处理器
     */
    on(event, handler) {
        if (!this.handlers.has(event)) {
            this.handlers.set(event, []);
        }
        this.handlers.get(event).push(handler);
        return this;
    }

    /**
     * 移除事件处理器
     */
    off(event, handler) {
        if (this.handlers.has(event)) {
            const handlers = this.handlers.get(event);
            const index = handlers.indexOf(handler);
            if (index > -1) {
                handlers.splice(index, 1);
            }
        }
        return this;
    }

    /**
     * 触发事件
     */
    _emit(event, data) {
        if (this.handlers.has(event)) {
            this.handlers.get(event).forEach(handler => {
                try {
                    handler(data);
                } catch (e) {
                    console.error('[NIO] 事件处理器错误:', e);
                }
            });
        }
    }

    /**
     * 处理收到的消息
     */
    _handleMessage(raw) {
        try {
            const message = JSON.parse(raw);

            // 检查是否是待处理请求的响应
            if (message.id && this.pendingRequests.has(message.id)) {
                const { resolve, timer } = this.pendingRequests.get(message.id);
                clearTimeout(timer);
                this.pendingRequests.delete(message.id);
                resolve(message);
                return;
            }

            // 根据类型分发事件
            const eventType = message.type || 'message';
            this._emit(eventType, message);
            this._emit('message', message);

        } catch (e) {
            console.error('[NIO] 消息解析错误:', e);
        }
    }

    /**
     * 刷新消息队列
     */
    _flushQueue() {
        while (this.messageQueue.length > 0 && this.connected) {
            const message = this.messageQueue.shift();
            this.ws.send(JSON.stringify(message));
        }

        // 重新订阅
        this.subscriptions.forEach(target => {
            this.send('subscribe', { target });
        });
    }

    /**
     * 尝试重连
     */
    _tryReconnect() {
        if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
            console.log('[NIO] 达到最大重连次数，停止重连');
            this._emit('reconnect_failed');
            return;
        }

        this.reconnectAttempts++;
        console.log(`[NIO] ${this.options.reconnectInterval}ms 后尝试重连 (${this.reconnectAttempts}/${this.options.maxReconnectAttempts})`);

        setTimeout(() => {
            this.connect().catch(() => {
                // 连接失败会触发 onclose，继续重连
            });
        }, this.options.reconnectInterval);
    }

    /**
     * 启动心跳
     */
    _startHeartbeat() {
        this._stopHeartbeat();
        this.heartbeatTimer = setInterval(() => {
            if (this.connected) {
                this.send('heartbeat');
            }
        }, this.options.heartbeatInterval);
    }

    /**
     * 停止心跳
     */
    _stopHeartbeat() {
        if (this.heartbeatTimer) {
            clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }
}


/**
 * NIO 屏幕控制器
 * 封装屏幕相关操作
 */
class NIOScreenController {
    constructor(channel, canvas) {
        this.channel = channel;
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.running = false;
        this.lastFrame = null;
        this.fps = 0;
        this.frameCount = 0;
        this.lastFpsTime = Date.now();

        // 绑定事件
        this.channel.on('screenshot', (msg) => this._onScreenshot(msg));
    }

    /**
     * 开始屏幕流
     */
    start(interval = 50) {
        if (this.running) return;
        this.running = true;
        this.channel.subscribe('screenshot', { interval });
        console.log('[NIO Screen] 开始屏幕流');
    }

    /**
     * 停止屏幕流
     */
    stop() {
        if (!this.running) return;
        this.running = false;
        this.channel.unsubscribe('screenshot');
        console.log('[NIO Screen] 停止屏幕流');
    }

    /**
     * 处理截图
     */
    _onScreenshot(msg) {
        if (!this.running || msg.status !== 'ok') return;

        const img = new Image();
        img.onload = () => {
            // 调整 canvas 大小
            if (this.canvas.width !== img.width || this.canvas.height !== img.height) {
                this.canvas.width = img.width;
                this.canvas.height = img.height;
            }
            this.ctx.drawImage(img, 0, 0);
            this.lastFrame = Date.now();

            // 计算 FPS
            this.frameCount++;
            const now = Date.now();
            if (now - this.lastFpsTime >= 1000) {
                this.fps = this.frameCount;
                this.frameCount = 0;
                this.lastFpsTime = now;
            }
        };
        img.src = 'data:image/jpeg;base64,' + msg.data;
    }

    /**
     * 发送触摸事件
     */
    touch(x, y) {
        this.channel.send('touch', { x, y });
    }

    /**
     * 发送滑动事件
     */
    swipe(x1, y1, x2, y2, duration = 200) {
        this.channel.send('swipe', { x1, y1, x2, y2, duration: duration / 1000 });
    }

    /**
     * 发送文字输入
     */
    input(text) {
        this.channel.send('input', { text });
    }

    /**
     * 发送按键事件
     */
    keyevent(key) {
        this.channel.send('keyevent', { key });
    }
}


// 导出
window.NIOChannel = NIOChannel;
window.NIOScreenController = NIOScreenController;
