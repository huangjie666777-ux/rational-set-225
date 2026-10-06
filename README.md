# 数学公式排版与有理式演算核验后端

将结构化公式树排版为单行、自包含的 SVG（仅含字形轮廓路径与横线矩形，
不依赖字体文件、外链、脚本或 foreignObject）。使用
fonts/STIXTwoMath-Regular.otf 的真实字形轮廓、前进宽度、斜体修正与
OpenType MATH 表度量，不做等宽估算。另提供 POST /check 有理式演算核验，
供教师核对学生约分、通分等步骤的值与实数定义域。另提供 POST /solve
有理式不等式（组）求解：给出实数解集与完整符号表，供教师备课确定
全部解，而不只是核对变形。

## 运行

    .venv/bin/uvicorn rational_set225.app:app --port 8123

## 接口

POST /render

    {
      "font_size": 48,
      "formula": { "type": "...", ... }
    }

返回 200:

    { "svg": "<svg ...>", "width": 196.03, "height": 121.92, "baseline": 82.56 }

width / height / baseline（基线距 SVG 顶部的距离）与 font_size 同一单位。
校验失败返回 422 与 {"detail": "..."}，不交付半成品。

POST /check 有理式演算核验：提交 2 至 10 个相邻演算步骤与字号，逐步骤
返回精确分子/分母多项式、实数定义域禁取点与按原式排版的 SVG 尺寸，并对
每对相邻步骤给出核验结论。

    {
      "font_size": 48,
      "steps": [
        {"type":"div","left":{"type":"var"},
         "right":{"type":"sub","left":{"type":"var"},
                                      "right":{"type":"num","n":1}}},
        ...
      ]
    }

返回:

    {
      "steps": [{"numerator":"x","denominator":"x - 1",
                 "forbidden": [{"kind":"rational","value":"1","approx":1.0}],
                 "svg":"<svg ...>","width":..,
                 "height":..,
                 "baseline":..}, ...],
      "comparisons": [
        {"verdict":"identical",
         "identical_on_common_domain": true, "same_domain": true,
         "added_forbidden": [], "removed_forbidden": [],
         "cross_product_difference": "0"}, ...]
    }

verdict 三态：

- identical：公共定义域上有理函数恒等，且禁取点集合完全相同。
- same_value_domain_changed：公共定义域上恒等（交叉乘积差多项式为 0），
  但定义域变化；added_forbidden / removed_forbidden 给出新增与解除的点。
  约分抹掉限制会判为此态（例如 x/x → 1 解除 x=0）。
- not_identical：不恒等；cross_product_difference 为 N1·D2 − N2·D1 展开的
  整数系数差多项式，作为不恒等的代数证据（非抽样点判定）。

禁取点：kind=rational 时 value 为整数字符串或 "p/q" 分数；kind=algebraic
时 poly 为整系数不可约多项式、index 为 SymPy CRootOf 的实根序号、root 为
其精确实代数根表示，approx 仅供展示排序。根去重基于不可约因子的代数结构
（因子先在整数上分解后合并重数），不使用浮点容差。

POST /solve 有理式不等式（组）求解：提交 1 至 6 个同时成立的条件与字号，
返回实数解集、符号表，以及每个条件按原树排版（含关系符号）的 SVG 尺寸。

    {
      "font_size": 48,
      "conditions": [
        {"left":  <表达式树>, "right": <表达式树>, "relation": "gt"},
        {"left":  <表达式树>, "right": <表达式树>, "relation": "le"}
      ]
    }

relation 取 eq/ne/lt/le/gt/ge。表达式树与 /check 完全相同（同一套节点、
输入限制与精确运算，不解析字符串）；每个条件按 left-right 构造差式，
继承两边每个原始子式的禁取值——约分、嵌套除法与零次幂都不能解除它们。

返回:

    {
      "conditions": [
        {"relation": "gt",
         "difference": {"numerator": "1", "denominator": "x - 2"},
         "zeros": [...], "forbidden": [...],
         "svg": "<svg ...>", "width": .., "height": .., "baseline": ..}
      ],
      "sign_table": {
        "critical_points": [...],
        "intervals": [
          {"lower": {"kind": "infinity", "sign": "negative"},
           "upper": {"kind": "point", "closed": false, "point": {...}},
           "sample": "0",
           "differences": ["positive"],
           "satisfied": [true],
           "all_satisfied": true}, ...
        ],
        "points": [
          {"point": {...},
           "differences": ["zero" | "positive" | "negative" | "undefined"],
           "defined": [true], "satisfied": [...], "all_satisfied": ...}, ...
        ]
      },
      "solution_set": {
        "kind": "set" | "empty" | "all",
        "parts": [
          {"type": "interval",
           "lower": {"kind": "point", "closed": true, "point": {...}}
                    | {"kind": "infinity", "sign": "negative"},
           "upper": ...},
          {"type": "point", "point": {...}}
        ]
      }
    }

求解规则：

- 临界点为各差式分子的实零点与全部禁取点的并集，精确去重排序
  （有理根按分数比较；代数根按不可约因子与 CRootOf 序号比较；
  有理数与代数根之间用 count_roots 在 (-oo, r] 上精确判定）。
- 每个开区间取一个精确有理数样本点（由隔离区间夹逼并验证）判定各差式
  正负；恒零差式记 "zero"。重根不会误判变号，因为符号来自采样而非
  奇偶性猜测。
- 临界点单独判断：是该条件禁取点则记 "undefined"（条件不成立），否则
  精确判定差式符号，区分等号成立与表达式无定义。
- solution_set 为满足全部条件的互不重叠最大区间与孤立点；端点标明
  开闭与正负无穷；空集 kind="empty"，全实轴 kind="all"。有限端点只用
  精确有理数或实代数根，不用浮点容差合并近根，不以浮点网格抽样代替
  求解；任何求不出全解的输入都会报错而不是返回部分成功。

备课示例（(x-1)/(x-2) > 0 且 x^2 - 2 >= 0）:

    curl -X POST localhost:8123/solve -H 'Content-Type: application/json' -d '{
      "font_size": 48,
      "conditions": [
        {"left": {"type":"div","left":{"type":"sub","left":{"type":"var"},
            "right":{"type":"num","n":1}},
          "right":{"type":"sub","left":{"type":"var"},
            "right":{"type":"num","n":2}}},
         "right": {"type":"num","n":0}, "relation": "gt"},
        {"left": {"type":"sub",
            "left":{"type":"pow","base":{"type":"var"},"exp":2},
            "right":{"type":"num","n":2}},
         "right": {"type":"num","n":0}, "relation": "ge"}
      ]}'

解集为 (-inf, -sqrt(2)] u (2, +inf)：第一部分上端点为代数根
CRootOf(x**2 - 2, 0)（闭），第二部分下端点为有理数 2（开）。

## 有理式表达式树

仅接受以下结构化节点；任何字符串表达式或代码一律拒绝：

- {"type":"num","n":整数,"d":非零整数}  有理常数，d 省略视为 1
- {"type":"var"}  变量 x
- {"type":"add"|"sub"|"mul"|"div","left":E,"right":E}
- {"type":"pow","base":E,"exp":0..6 的整数}

核验规则与限制：

- 全部运算在 SymPy 整数系数多项式上精确进行（ZZ 域），无浮点比较。
- 每个原始子式除数的零点都登记为禁取值；约分只影响 N/D 展示，不抹掉限制。
- 嵌套除法保留内层除数限制；0 次幂 base^0 保留 base 自身全部限制
  （含嵌套除数与 base 分子零点）。恒零除数（含可化简为 0，如 1/(x−x)）
  直接拒绝。
- 单树至多 200 个节点、嵌套深 20；每次二元/幂运算后中间分子、分母次数
  至多 12，越界拒绝。整数字面量至多 100 位。输入树不被修改。
- 排版按原式结构生成既有节点（分式、乘除、幂与必要括号），不用约分结果
  替换原式；负常数、连减右操作数、作为幂底的复合式等处自动补括号。

## 节点格式

- {"type":"text","value":"x+1"}        纯文本（仅字体覆盖的字符）
- {"type":"row","children":[...]}      横向序列，基线对齐
- {"type":"frac","num":N,"den":N}      分式，横线居中于数学轴
- {"type":"scripts","base":N,"sup":N?,"sub":N?}  上标/下标，可单独或同时出现
- {"type":"sqrt","radicand":N}         平方根，横线覆盖被开方内容
- {"type":"paren","child":N,"left":"(","right":")"}  括号包围；
  left/right 可选 ( ) [ ] { } |，默认圆括号

节点可任意组合嵌套。上下标随层级按 MATH 表 ScriptPercentScaleDown /
ScriptScriptPercentScaleDown 缩小，同现时保持最小间距并计入基字斜体修正。
括号与根号高度超出普通符号时先选伸展变体（.s1...sN），再按 GlyphAssembly
连接信息拼装伸展部件，绝不纵向拉伸完整字形。嵌套后外层尺寸自动重算，
viewBox 按全部墨迹与横线的实际包围盒计算，不发生裁切。

## 示例

    curl -X POST localhost:8123/render -H 'Content-Type: application/json' -d '{
      "font_size": 48,
      "formula": {"type":"paren","child":{"type":"row","children":[
        {"type":"scripts","base":{"type":"text","value":"x"},
                           "sup":{"type":"text","value":"2"}},
        {"type":"text","value":"+"},
        {"type":"frac","num":{"type":"text","value":"1"},
          "den":{"type":"sqrt","radicand":
            {"type":"scripts","base":{"type":"text","value":"y"},
                              "sub":{"type":"text","value":"i"}}}}
      ]}}}'

## 自测

    .venv/bin/python -m rational_set225.selftest

## 代码结构

- rational_set225/font.py    字体读取：度量、MATH 常量、轮廓路径、伸展变体与拼装
- rational_set225/nodes.py   排版树校验（深度/节点数/字号/字符覆盖限制）
- rational_set225/expr.py    有理式树校验、精确有理运算、禁取点实根、逐步比较
- rational_set225/solve.py   不等式组求解：临界点精确排序、区间采样符号表、解集归并
- rational_set225/typeset.py 有理式树到既有排版节点的转换
- rational_set225/layout.py  递归布局：行、分式、上下标、根号、括号（伸展件按墨迹钳制覆盖）
- rational_set225/svg.py     SVG 绘制与包围盒/基线计算
- rational_set225/app.py     FastAPI HTTP 交付（/render、/check 与 /solve）
- rational_set225/selftest.py 自测

## 范围与限制

- 仅处理字体覆盖的文字；不解析 LaTeX，不做换行，输出恒为单行。
- 缺字、未知节点、缺子项、非有限或非正字号、过深（>64 层）或过大
  （>5000 节点）的输入一律拒绝。
- 排版结果确定：同一输入产生完全相同的 SVG；输入树不被修改。
- /check 仅处理单变量 x 的有理函数（由上述节点构成）；无理式、多变量、
  表达式字符串与代码均不支持；2..10 步、节点/深度/次数超限返回 422。
