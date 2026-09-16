const axios = require("axios");
class WeChatCodeServer {
    constructor(options) {
        this.serverUrl = options.url;
        this.appid = options.appid;
        this.auth = options.auth;
    }

    _parseYyb(openid) {
        if (typeof openid !== 'string' || !openid.includes('@')) return null;
        const atIndex = openid.indexOf('@');
        let server = openid.substring(0, atIndex).trim();
        const ref = openid.substring(atIndex + 1).trim();
        if (!server || !ref) return null;
        if (server.startsWith('http://')) server = server.substring(7);
        else if (server.startsWith('https://')) server = server.substring(8);
        server = server.replace(/\/+$/, '');
        if (!server) return null;
        return { server, ref };
    }

    getCode(openid) {
        const yyb = this._parseYyb(openid);
        if (yyb) {
            console.log('YYB-Go 取code: ' + yyb.server + '/' + yyb.ref);
            const url = 'http://' + yyb.server + '/wxapp/getCode';
            return new Promise((resolve, reject) => {
                axios.post(url, { ref: yyb.ref, app_id: this.appid }, {
                    timeout: 30 * 1000
                }).then(res => {
                    const code = res.data?.data?.result?.code || res.data?.code;
                    if (!code) {
                        console.log('YYB-Go 返回无code: ' + JSON.stringify(res.data));
                    }
                    resolve({ data: { code: code || "" } });
                }).catch(err => {
                    reject(err);
                });
            });
        }
        console.log('等待获取code:');
        return new Promise((resolve, reject) => {
            axios.post(this.serverUrl + '/wx/code', { appid: this.appid, openid }, {
                headers: { 'auth': this.auth },
                timeout: 30 * 1000
            }).then(res => {
                console.log('获取code成功:');
                resolve(res);
            }).catch(err => {
                reject(err);
            });
        });
    }

    cloudInit(openid) {
        const yyb = this._parseYyb(openid);
        if (yyb) {
            const url = 'http://' + yyb.server + '/wxapp/cloud/init';
            return new Promise((resolve, reject) => {
                axios.post(url, { ref: yyb.ref, app_id: this.appid }, {
                    timeout: 30 * 1000
                }).then(res => resolve(res))
                 .catch(err => reject(err));
            });
        }
        console.log('等待云函数初始化:');
        return new Promise((resolve, reject) => {
            axios.post(this.serverUrl + '/wx/call/init', { appid: this.appid, openid }, {
                headers: { 'auth': this.auth },
                timeout: 30 * 1000
            }).then(res => {
                console.log('云函数初始化成功:');
                resolve(res);
            }).catch(err => reject(err));
        });
    }

    cloudCall(openid) {
        const yyb = this._parseYyb(openid);
        if (yyb) {
            const url = 'http://' + yyb.server + '/wxapp/cloud/call';
            return new Promise((resolve, reject) => {
                axios.post(url, { ref: yyb.ref, app_id: this.appid }, {
                    timeout: 30 * 1000
                }).then(res => resolve(res))
                 .catch(err => reject(err));
            });
        }
        console.log('等待云函数调用:');
        return new Promise((resolve, reject) => {
            axios.post(this.serverUrl + '/wx/cloud/call', { appid: this.appid, openid }, {
                headers: { 'auth': this.auth },
                timeout: 30 * 1000
            }).then(res => {
                console.log('云函数调用成功:');
                resolve(res);
            }).catch(err => reject(err));
        });
    }

    getPhoneNumber(openid) {
        const yyb = this._parseYyb(openid);
        if (yyb) {
            const url = 'http://' + yyb.server + '/wxapp/getPhoneNumber';
            return new Promise((resolve, reject) => {
                axios.post(url, { ref: yyb.ref, app_id: this.appid }, {
                    timeout: 30 * 1000
                }).then(res => resolve(res))
                 .catch(err => reject(err));
            });
        }
        return new Promise((resolve, reject) => {
            axios.post(this.serverUrl + '/wx/getPhoneNumber', { appid: this.appid, openid }, {
                headers: { 'auth': this.auth },
                timeout: 30 * 1000
            }).then(res => resolve(res))
             .catch(err => reject(err));
        });
    }
}
module.exports = WeChatCodeServer;
