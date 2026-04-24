## Renta! Downloader
从Renta! 下载电子书

* 登入支持
* 模拟iOS客户端
* 下载完整的ePub文件
* 将漫画重封装为CBZ
* 下载动漫与音声（Renta! Taiwan）
* 下载絵ノベル并封装为ePub文件
* 异步并发下载

## 支持商店地区
- [x] Renta! Japan
- [x] Renta! Taiwan
- [ ] Renta! Global

## 环境要求
* Python 3.8+

## 使用方法
1. clone本项目
2. 创建并激活虚拟环境
   ```shell
   python -m venv .venv

   # Windows CMD
   call .venv\Scripts\activate.bat 

   # Windows Powershell
   .\.venv\Scripts\Activate.ps1

   # Linux / macOS
   source venv/bin/activate
   ```
3. 安装依赖
   ```shell 
   pip install -r requirements.txt
   ```
4. 开始使用
   ```shell
   python renta_japan.py --help # Renta! Japan
   python renta_taiwan.py --help # Renta! Taiwan
   ```
5. 附加组件
   ```shell
   # 如果需要在Renta! Taiwan下载动画和音声
   # 则需要安装streamlink或yt-dlp
   pip install streamlink # streamlink
   pip install yt-dlp # yt-dlp
   ```

## 指令
### login
> 登入你的Renta! 账号
> 
> Cookies保存在`renta_japan_cookies.lwp`
* --email *TEXT*
* --password *TEXT*

不带选项运行该指令时会要求用户输入Email和密码

---
### logout
> 移除本地保存的登入Cookies
---
### login-check
> 访问账号主页，查看是否被重定向到登入页
>
> 据此检查当前的Cookies是否有效
---
### series
> 列出指定系列的所有作品
>
> （必须登入）
* series_id
  * **[Japan]** renta.papy.co.jp/renta/sc/frm/item/***123456***
  * **[Taiwan]** tw.myrenta.com/item/***123456***
  * 输入这串数字，或直接输入整个URL

用法示例
```shell
python renta_client.py series 123456
```
---
### download-series
> 下载指定系列中所有可下载的作品
> 
> （必须登入）
* series_id
  * 同上
* --output PATH
  * 指定输出文件夹
  * 不指定时默认为`当前工作目录/output`
* **[Japan ONLY]** --descramble / --no-descramble
  * 启用JSImg View的反混淆
  * **不推荐**，默认为 `--no-descramble`
  ```plaintext
  对于免费漫画，Renta只允许使用JSImg View打开
  但是该模式下无法获得原图，只有被混淆过的切片图像，JPEG质量70左右，很差
  启用该选项后，将拼凑回完整图像，并保存为PNG
  ```
* **[Japan ONLY]** --legacy-web / --no-legacy-web
  * 阅读免费文学作品时，使用传统Web端ePub阅读器 (view_epub2) 而非新阅读器 (view_novel)
  * **推荐**，默认为 `--legacy-web`
  ```plaintext
  传统阅读器可以获取完整的ePub文件，与购买后下载的一致
  新阅读器无法定位CSS文件，不能保证所有Style均一致
  目前新阅读器的ePub重组功能仍是实验性的
  ```
* **[Japan ONLY]** --proxy URL
  * 代理服务器地址
  * Renta! Japan在中国大陆也可直接访问

### [Taiwan ONLY] config
> 设置全局代理
>
> Web可能需要，App基本可以直接连接
* proxy_url

## 输出一览表
* Renta! Japan

  | 购买情况 | 类型 | 下载途径 | 输出格式 |
  | --- | --- | --- | --- |
  | 免费 | 文学 | view_epub2<br>~~view_novel~~ | ePub（逐文件） |
  | 租借/购入 | 文学 | view_pack | ePub（完整） |
  | 免费 | 纯图像 | view_jsimg5 | CBZ（非原图）| 
  | 租借/购入 | 纯图像 | view_pack | CBZ（原图）|
  | Any | 絵ノベル | view_novel | ePub（合成） |

* Renta! Taiwan 

  | 平台 | 类型 | 输出格式 |
  | --- | --- | --- |
  | WEB | 文学 | ePub（逐文件） |
  | WEB | 纯图像 | CBZ（非原图）| 
  | WEB | 动画 | MP4（HLS） |
  | APP | 文学 | ePub（完整） |
  | APP | 纯图像 | ePub（完整） |
  | APP | 动画 | 不支持 |

## TODO
- [x] 支持Taiwan站点
- [ ] 支持Global站点
- [ ] 全局PROXY设置