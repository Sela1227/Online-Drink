/**
 * 首頁自動刷新功能
 * 
 * 當有團單截止時，自動局部刷新團單列表
 * 
 * 使用方式：
 * 1. 在 home.html 的 <body> 或 <script> 中引入此邏輯
 * 2. 設定 data-next-deadline 屬性
 */

// Alpine.js component for auto-refresh
document.addEventListener('alpine:init', () => {
    Alpine.data('homeAutoRefresh', (nextDeadlineISO) => ({
        nextDeadline: nextDeadlineISO ? new Date(nextDeadlineISO + 'Z') : null,
        refreshTimer: null,
        
        init() {
            if (this.nextDeadline) {
                this.scheduleRefresh();
            }
        },
        
        scheduleRefresh() {
            const now = new Date();
            const diff = this.nextDeadline - now;
            
            if (diff <= 0) {
                // 已經過期，立即刷新
                this.doRefresh();
            } else if (diff < 60000) {
                // 1 分鐘內截止，設定精確計時器
                this.refreshTimer = setTimeout(() => {
                    this.doRefresh();
                }, diff + 1000); // 多等 1 秒確保過期
            } else {
                // 超過 1 分鐘，每分鐘檢查一次
                this.refreshTimer = setTimeout(() => {
                    this.scheduleRefresh();
                }, 60000);
            }
        },
        
        doRefresh() {
            // 使用 HTMX 局部刷新
            const groupList = document.getElementById('group-list');
            if (groupList) {
                htmx.ajax('GET', '/home/groups', {
                    target: '#group-list',
                    swap: 'innerHTML'
                });
            }
            
            // 刷新後重新計算下一個截止時間
            // 這個會在 HTMX 回應後由後端更新
        },
        
        destroy() {
            if (this.refreshTimer) {
                clearTimeout(this.refreshTimer);
            }
        }
    }));
});


/**
 * 倒數計時器增強版
 * 
 * 當倒數結束時觸發首頁刷新
 */
function countdownWithRefresh(deadline) {
    return {
        deadline: new Date(deadline + 'Z'),
        display: '',
        interval: null,
        
        init() {
            this.update();
            this.interval = setInterval(() => this.update(), 1000);
        },
        
        update() {
            const now = new Date();
            const diff = this.deadline - now;
            
            if (diff <= 0) {
                this.display = '已截止';
                clearInterval(this.interval);
                
                // 觸發首頁刷新
                setTimeout(() => {
                    const groupList = document.getElementById('group-list');
                    if (groupList) {
                        htmx.ajax('GET', '/home/groups', {
                            target: '#group-list',
                            swap: 'innerHTML'
                        });
                    }
                }, 1000);
                
                return;
            }
            
            const hours = Math.floor(diff / 3600000);
            const minutes = Math.floor((diff % 3600000) / 60000);
            const seconds = Math.floor((diff % 60000) / 1000);
            
            if (hours > 0) {
                this.display = `剩 ${hours}h ${minutes}m`;
            } else if (minutes > 0) {
                this.display = `剩 ${minutes}m ${seconds}s`;
            } else {
                this.display = `剩 ${seconds}s`;
            }
        },
        
        destroy() {
            if (this.interval) {
                clearInterval(this.interval);
            }
        }
    };
}
