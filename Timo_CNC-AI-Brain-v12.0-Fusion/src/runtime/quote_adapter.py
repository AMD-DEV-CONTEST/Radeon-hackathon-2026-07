"""
CNC报价引擎 v3.0 — 完全还原手工报价4.xlsx逻辑

Excel公式 N27:
  = SUM(L24, M15, O6, L20) / (1 - H27) * L27
  
  L24 = 测量费+夹治具费+刀具费+其他费
  M15 = SUM(各工艺加工费) = rate*hours*prec*rough
  O6  = 毛坯重量(kg) * 材料单价(元/kg)
  L20 = 表面处理费(按重量或按数量)
  H27 = 利润率
  L27 = 折扣系数
"""

import yaml, re
from pathlib import Path
from typing import Dict, Any, Optional
from src.neuro_core.reasoning_chain import ReasoningChain, register_chain

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class QuoteAdapter:
    """CNC报价引擎 v3.0"""

    def __init__(self):
        self._load_materials()
        self._load_tolerance()
        self._load_machining_rates()
        self._load_surface_rates()
        self._load_measurement_rates()

    def _load_materials(self):
        """材料数据库 (匹配Excel Database表)"""
        self.materials = {
            "AL6061":  {"price_kg": 30,  "density": 2.8,  "wire_cut": 2.5, "name": "6061铝合金"},
            "AL7075":  {"price_kg": 40,  "density": 2.8,  "wire_cut": 2.5, "name": "7075铝合金"},
            "AL2024":  {"price_kg": 50,  "density": 2.78, "wire_cut": 2.5, "name": "2024铝合金"},
            "AL5052":  {"price_kg": 35,  "density": 2.68, "wire_cut": 2.5, "name": "5052铝合金"},
            "SUS304":  {"price_kg": 30,  "density": 7.85, "wire_cut": 1.0, "name": "304不锈钢"},
            "SUS316":  {"price_kg": 40,  "density": 7.85, "wire_cut": 1.0, "name": "316不锈钢"},
            "SS440C":  {"price_kg": 60,  "density": 7.75, "wire_cut": 3.0, "name": "440C不锈钢"},
            "17-4PH":  {"price_kg": 120, "density": 7.78, "wire_cut": 4.0, "name": "17-4PH不锈钢"},
            "S45C":    {"price_kg": 12,  "density": 7.85, "wire_cut": 1.0, "name": "45号钢"},
            "Q235":    {"price_kg": 10,  "density": 7.85, "wire_cut": 1.0, "name": "Q235钢"},
            "CRS":     {"price_kg": 15,  "density": 7.85, "wire_cut": 1.0, "name": "冷轧钢"},
            "PC":      {"price_kg": 45,  "density": 1.1,  "wire_cut": 2.0, "name": "聚碳酸酯PC"},
            "PMMA":    {"price_kg": 35,  "density": 1.1,  "wire_cut": 2.0, "name": "有机玻璃"},
            "ABS":     {"price_kg": 25,  "density": 1.1,  "wire_cut": 2.0, "name": "ABS塑料"},
            "PEEK":    {"price_kg": 800, "density": 1.4,  "wire_cut": 3.0, "name": "PEEK"},
            "H65":     {"price_kg": 80,  "density": 8.6,  "wire_cut": 2.5, "name": "H65黄铜"},
            "TC4":     {"price_kg": 180, "density": 4.5,  "wire_cut": 5.0, "name": "钛合金TC4"},
            "INCONEL": {"price_kg": 600, "density": 8.44, "wire_cut": 6.0, "name": "因科镍合金"},
            "HASTELLOY": {"price_kg": 500, "density": 8.89, "wire_cut": 6.0, "name": "哈氏合金"},
            "POM":     {"price_kg": 30,  "density": 1.41, "wire_cut": 2.0, "name": "聚甲醛POM"},
            "NYLON":   {"price_kg": 40,  "density": 1.14, "wire_cut": 2.0, "name": "尼龙PA"},
            "PTFE":    {"price_kg": 150, "density": 2.15, "wire_cut": 3.0, "name": "聚四氟乙烯"},
            "PEI":     {"price_kg": 300, "density": 1.27, "wire_cut": 3.0, "name": "聚醚酰亚胺"},
        }
        self.material_aliases = {
            "304": "SUS304", "不锈钢": "SUS304", "316": "SUS316",
            "6061": "AL6061", "6061-T6": "AL6061", "铝合金": "AL6061",
            "7075": "AL7075", "2024": "AL2024", "5052": "AL5052",
            "45钢": "S45C", "45#": "S45C", "碳钢": "S45C",
            "黄铜": "H65", "铜": "H65", "钛": "TC4",
            "冷轧钢": "CRS", "SPCC": "CRS", "440C": "SS440C", "17-4": "17-4PH",
            "聚甲醛": "POM", "赛钢": "POM", "尼龙": "NYLON", "PA": "NYLON",
            "特氟龙": "PTFE", "铁氟龙": "PTFE", "聚醚酰亚胺": "PEI",
            "哈氏": "HASTELLOY", "因科镍": "INCONEL",
        }

    def _load_tolerance(self):
        """精度/粗糙度系数 (匹配Database表 C33:D36, C40:D43)"""
        self.precision_grades = {
            "2768-M&F": 1.0, "0.05-0.03": 1.2,
            "0.03-0.01": 1.5, "0.01-0.005": 2.5,
            "IT4": 1.9, "IT5": 1.8, "IT6": 1.5, "IT7": 1.2,
            "IT8": 1.0, "IT9": 0.9, "IT10": 0.85,
        }
        self.roughness_grades = {
            "Ra1.6&Ra3.2": 1.0, "Ra 0.8": 1.2,
            "Ra 0.4": 1.5, "Ra 0.4以下": 2.0,
        }

    def _load_machining_rates(self):
        """加工工艺费率 (匹配Database表 C20:D28)"""
        self.machining_rates = {
            "三轴CNC": {"rate": 1.0,  "unit": "time"},
            "四轴CNC": {"rate": 1.33, "unit": "time"},
            "五轴CNC": {"rate": 3.0,  "unit": "time"},
            "车加工":   {"rate": 1.0,  "unit": "time"},
            "铣加工":   {"rate": 1.0,  "unit": "time"},
            "放电":     {"rate": 2.0,  "unit": "time"},
            "线切割":   {"rate": 0.0,  "unit": "length"},
            "外圆磨":   {"rate": 3.33, "unit": "time"},
            "内孔磨":   {"rate": 1.67, "unit": "time"},
            "平面磨":   {"rate": 1.0,  "unit": "time"},
        }
        self.wire_prices = {
            "快丝": 0.005, "慢丝割一修一": 0.026, "慢丝割一修二": 0.030,
        }
        self.base_hourly_rate = 120

    def _load_surface_rates(self):
        """表面处理费率 (匹配Database表 C47:E52)"""
        self.surface_rates = {
            "阳极氧化":       {"by_quantity": 4,   "by_weight": 25},
            "硬氧":           {"by_quantity": 6,   "by_weight": 35},
            "自定义颜色阳极": {"by_quantity": 300, "by_weight": 300},
            "喷油/粉":       {"by_quantity": 300, "by_weight": 300},
            "电镀铬/锌/镍":  {"by_quantity": 50,  "by_weight": 100},
            "热处理":        {"by_quantity": 50,  "by_weight": 10},
        }
        self.surface_aliases = {
            "阳极氧化本色": "阳极氧化", "阳极氧化黑色": "自定义颜色阳极",
            "阳极": "阳极氧化", "导电氧化": "阳极氧化", "普通氧化": "阳极氧化",
            "硬质阳极氧化": "硬氧", "硬质氧化": "硬氧",
            "电镀": "电镀铬/锌/镍", "镀镍": "电镀铬/锌/镍",
            "镀锌": "电镀铬/锌/镍", "化学镀镍": "电镀铬/锌/镍",
            "镀硬铬": "电镀铬/锌/镍",
            "电泳": "喷油/粉", "达克罗": "喷油/粉",
            "喷砂": "喷油/粉", "抛光": "喷油/粉",
            "发黑": "阳极氧化", "钝化": "阳极氧化",
            "渗氮": "热处理",
        }

    def _load_measurement_rates(self):
        """测量费用 (匹配Database表 C56:D58)"""
        self.measurement_rates = {"标准": 0, "FAI": 100, "CMM": 150, "SPC": 80}

    def resolve_material(self, material_raw):
        m = material_raw.strip()
        m_lower = m.lower()
        # 精确匹配（忽略大小写）
        if m_lower in self.material_aliases:
            return self.material_aliases[m_lower]
        for key in self.materials:
            if key.lower() == m_lower:
                return key
        # 前缀匹配: "6061-t6" 匹配别名 "6061"
        for alias, mat_key in self.material_aliases.items():
            if m_lower.startswith(alias.lower()) or alias.lower().startswith(m_lower):
                return mat_key
        return material_raw

    def resolve_surface(self, surface):
        if not surface or surface in ("无", "none", "None", ""):
            return None
        s = surface.strip()
        if s in self.surface_rates:
            return s
        if s in self.surface_aliases:
            return self.surface_aliases[s]
        # 子串匹配：用户输入"阳极氧化"可命中别名"阳极"
        s_lower = s.lower()
        for alias, mapped in self.surface_aliases.items():
            if alias.lower() in s_lower or s_lower in alias.lower():
                return mapped
        for key in self.surface_rates:
            if key.lower() == s_lower:
                return key
        for key in self.surface_aliases:
            if key.lower() == s_lower:
                return self.surface_aliases[key]
        return None

    def calc_weight_from_dimensions(self, shape, dimensions, material):
        """根据形状和尺寸计算重量(kg) - 匹配Excel O6公式，按密度计算"""
        mat_info = self.materials.get(material, {"density": 2.8})
        density = mat_info["density"]
        # None 防护：键存在但值为 None 时回退为空字典
        dimensions = dimensions or {}
        shape_l = shape.lower()

        if shape_l in ("flat", "plate"):
            L = dimensions.get("L", dimensions.get("l", 50))
            W = dimensions.get("W", dimensions.get("w", 50))
            H = dimensions.get("H", dimensions.get("t", dimensions.get("h", 10)))
            vol_cm3 = L * W * H / 1000
        elif shape_l in ("round", "cylinder", "shaft"):
            D = dimensions.get("D", dimensions.get("d", 50))
            H = dimensions.get("H", dimensions.get("L", dimensions.get("l", 50)))
            vol_cm3 = 3.14159 * (D / 2) ** 2 * H / 1000
        elif shape_l in ("flange", "disc"):
            # 法兰/圆盘：按外径-内径环形截面积 × 厚度
            od = dimensions.get("D", dimensions.get("od", 100))
            id_ = dimensions.get("d", dimensions.get("id", 50))
            t = dimensions.get("H", dimensions.get("t", dimensions.get("thickness", 20)))
            vol_cm3 = 3.14159 * ((od / 2) ** 2 - (id_ / 2) ** 2) * t / 1000
        elif shape_l in ("sleeve", "bushing"):
            od = dimensions.get("D", dimensions.get("od", 60))
            id_ = dimensions.get("d", dimensions.get("id", 30))
            L = dimensions.get("L", dimensions.get("l", 80))
            vol_cm3 = 3.14159 * ((od / 2) ** 2 - (id_ / 2) ** 2) * L / 1000
        elif shape_l in ("pipe", "tube"):
            outer_D = dimensions.get("outer_D", dimensions.get("D", dimensions.get("d", 60)))
            inner_D = dimensions.get("inner_D", dimensions.get("d", 30))
            L = dimensions.get("L", dimensions.get("l", 50))
            area = 3.14159 * ((outer_D / 2) ** 2 - (inner_D / 2) ** 2)
            vol_cm3 = area * L / 1000
        elif shape_l in ("box", "block"):
            L = dimensions.get("L", dimensions.get("l", 100))
            W = dimensions.get("W", dimensions.get("w", 80))
            H = dimensions.get("H", dimensions.get("t", dimensions.get("h", 60)))
            vol_cm3 = L * W * H / 1000
        elif shape_l in ("bracket", "l"):
            # L型支架: 近似为两块板
            W = dimensions.get("W", dimensions.get("w", 80))
            H = dimensions.get("H", dimensions.get("h", 120))
            T = dimensions.get("T", dimensions.get("t", 10))
            L = dimensions.get("L", dimensions.get("l", 100))
            vol_cm3 = (W * L * T + H * L * T) / 1000
        else:
            L = dimensions.get("L", 50)
            W = dimensions.get("W", 50)
            H = dimensions.get("H", 10)
            vol_cm3 = L * W * H / 1000

        weight_kg = vol_cm3 * density / 1000
        return max(0.001, weight_kg)

    def quote(self, params):
        """CNC报价 - 完全还原Excel公式

        N27 = (L24 + M15 + O6 + L20) / (1 - H27) * L27
        """
        # 注：使用 "or 默认值" 而非 get(key, 默认值)，防止键存在但值为 None 时不触发默认值
        quantity = int(params.get("quantity") or 10)
        material_raw = params.get("material") or "AL6061"
        surface = params.get("surface_treatment", params.get("surface"))
        process = params.get("process") or "三轴CNC"
        tolerance = params.get("tolerance") or "IT8"
        shape = params.get("shape") or "flat"
        dimensions = params.get("dimensions") or {}

        material = self.resolve_material(material_raw)
        mat_info = self.materials.get(material, {
            "price_kg": 30, "density": 2.8, "wire_cut": 2.5, "name": material_raw
        })
        surface_key = self.resolve_surface(surface)

        # Step 1: weight
        if params.get("weight_kg") is not None and params.get("weight_kg") != '':
            weight_kg = float(params["weight_kg"])
        elif params.get("volume_cm3") is not None and params.get("volume_cm3") != '':
            weight_kg = float(params["volume_cm3"]) * mat_info["density"] / 1000
        else:
            weight_kg = self.calc_weight_from_dimensions(shape, dimensions, material)

        # Step 2: material cost O6 = weight * price (no 1.3 factor!)
        material_cost = weight_kg * mat_info["price_kg"]

        # Step 3: machining cost M15
        machining_hours_raw = params.get("machining_hours")
        if machining_hours_raw is not None and machining_hours_raw != '' and float(machining_hours_raw) > 0:
            machining_hours = float(machining_hours_raw)
        else:
            machining_hours = self.estimate_machining_hours(weight_kg, process, shape, tolerance)
        precision = params.get("precision", "2768-M&F")
        roughness = params.get("roughness", "Ra1.6&Ra3.2")
        wire_length = float(params.get("wire_length") or 0)

        proc_info = self.machining_rates.get(process, {"rate": 1.0, "unit": "time"})

        if proc_info["unit"] == "length":
            wire_price = self.wire_prices.get("快丝", 0.005)
            wire_height = float(params.get("wire_height") or weight_kg * 10)  # default height from weight
            machining_cost = wire_length * wire_height * wire_price
        else:
            rate = proc_info["rate"]
            prec_coef = self.precision_grades.get(precision, 1.0)
            rough_coef = self.roughness_grades.get(roughness, 1.0)
            machining_cost = self.base_hourly_rate * rate * machining_hours * prec_coef * rough_coef

        # Step 4: surface cost L20
        pricing_mode = params.get("pricing_mode", "by_quantity")
        surface_cost = 0.0
        if surface_key and surface_key in self.surface_rates:
            info = self.surface_rates[surface_key]
            if pricing_mode == "by_weight":
                surface_cost = weight_kg * info["by_weight"]
            else:
                surface_cost = info["by_quantity"] * quantity

        # Step 5: measurement/jig/tool L24
        measurement_type = params.get("measurement", "标准")
        jig_fee = float(params.get("jig_fee") or 0)
        tool_fee = float(params.get("tool_fee") or 0)
        other_fee = float(params.get("other_fee") or 0)
        measurement_fee = self.measurement_rates.get(measurement_type, 0)
        extra_fees = measurement_fee + jig_fee + tool_fee + other_fee

        # Step 6: final N27 = (L24 + M15 + O6 + L20) / (1 - H27) * L27
        profit_rate = float(params.get("profit_rate") or 0.30)
        discount = float(params.get("discount") or 1.0)

        total_cost = extra_fees + machining_cost + material_cost + surface_cost
        if profit_rate >= 1:
            final_price = total_cost * 10
        else:
            final_price = total_cost / (1 - profit_rate) * discount

        unit_price = final_price / quantity if quantity > 0 else final_price
        profit = final_price - total_cost
        lead_time = max(2, int(machining_hours * quantity / 8) + 2)

        return {
            "material": mat_info["name"],
            "material_code": material,
            "surface": surface_key or "无",
            "quantity": quantity,
            "process": process,
            "tolerance": tolerance,
            "shape": shape,
            "weight_kg": round(weight_kg, 4),
            "material_cost": round(material_cost, 2),
            "machining_cost": round(machining_cost, 2),
            "surface_cost": round(surface_cost, 2),
            "extra_fees": round(extra_fees, 2),
            "total_cost": round(total_cost, 2),
            "total_price": round(final_price, 2),  # 小计 = 单价×数量 = 总价
            "unit_price": round(unit_price, 2),
            "profit": round(profit, 2),
            "final_price": round(final_price, 2),
            "profit_rate": profit_rate,
            "discount": discount,
            "machine_hours": round(machining_hours, 2),
            "hourly_rate": round(self.base_hourly_rate * proc_info["rate"], 2) if proc_info["unit"] != "length" else 0,
            "tol_coef": self.precision_grades.get(precision, 1.0),
            "batch_discount": discount,
            "lead_time_days": lead_time,
            "pricing_mode": pricing_mode,
            "measurement": measurement_type,
            "measurement_fee": measurement_fee,
            "jig_fee": jig_fee,
            "tool_fee": tool_fee,
            "engine": "quote-v3.0 (Excel还原)",
        }

    def quote_with_reasoning(self, params):
        """
        CNC Quote WITH full reasoning chain (XAI).
        Shows every calculation step with formula references.
        """
        chain = ReasoningChain("quote", "CNC Machining Quote Calculation")

        # Step 1: Record all inputs
        for k, v in params.items():
            if v is not None and v != '':
                chain.add_input(k, v)

        quantity = int(params.get("quantity", 10))
        material_raw = params.get("material", "AL6061")
        surface = params.get("surface_treatment", params.get("surface"))
        process = params.get("process", "三轴CNC")
        tolerance = params.get("tolerance", "IT8")
        shape = params.get("shape", "flat")

        # Step 2: Material resolution
        material = self.resolve_material(material_raw)
        mat_info = self.materials.get(material, {"price_kg": 30, "density": 2.8, "wire_cut": 2.5, "name": material_raw})
        surface_key = self.resolve_surface(surface)

        chain.add_feature("material_resolved", material,
                         f"'{material_raw}' resolved to {mat_info['name']} ({material})")
        chain.add_feature("material_price", f"{mat_info['price_kg']} yuan/kg",
                         f"Unit price from material database")
        chain.add_feature("material_density", f"{mat_info['density']} g/cm3")

        # Step 3: Weight calculation
        if params.get("weight_kg") is not None and params.get("weight_kg") != '':
            weight_kg = float(params["weight_kg"])
            chain.add_calculation("Weight", f"Direct input: {weight_kg}kg", weight_kg, "kg",
                                 {"source": "user_input"})
        elif params.get("volume_cm3") is not None and params.get("volume_cm3") != '':
            weight_kg = float(params["volume_cm3"]) * mat_info["density"] / 1000
            chain.add_calculation("Weight", 
                                 f"Volume({params['volume_cm3']}cm3) * Density({mat_info['density']}g/cm3) / 1000",
                                 weight_kg, "kg",
                                 {"formula": "N27.O6", "volume_cm3": params["volume_cm3"]})
        else:
            weight_kg = self.calc_weight_from_dimensions(shape, params.get("dimensions", {}), material)
            chain.add_calculation("Weight (estimated from dimensions)", 
                                 f"Dimensions-based estimation for {shape}", weight_kg, "kg",
                                 {"source": "dimension_estimate"})

        # Step 4: Material cost (O6 = weight * price)
        material_cost = weight_kg * mat_info["price_kg"]
        chain.add_calculation("Material Cost (O6)",
                             f"{weight_kg:.4f}kg * {mat_info['price_kg']}yuan/kg",
                             material_cost, "yuan",
                             {"formula": "Excel O6 = weight * price_per_kg"})

        # Step 5: Machining cost (M15)
        machining_hours_raw = params.get("machining_hours")
        if machining_hours_raw is not None and machining_hours_raw != '' and float(machining_hours_raw) > 0:
            machining_hours = float(machining_hours_raw)
        else:
            machining_hours = self.estimate_machining_hours(weight_kg, process, shape, tolerance)

        proc_info = self.machining_rates.get(process, {"rate": 1.0, "unit": "time"})
        precision = params.get("precision", "2768-M&F")
        roughness = params.get("roughness", "Ra1.6&Ra3.2")
        prec_coef = self.precision_grades.get(precision, 1.0)
        rough_coef = self.roughness_grades.get(roughness, 1.0)

        if proc_info["unit"] == "length":
            wire_price = self.wire_prices.get("快丝", 0.005)
            wire_length = float(params.get("wire_length") or 0)
            wire_height = float(params.get("wire_height") or weight_kg * 10)
            machining_cost = wire_length * wire_height * wire_price
            chain.add_calculation("Machining Cost (M15 - wire cut)",
                                 f"Length({wire_length}) * Height({wire_height}) * Price({wire_price})",
                                 machining_cost, "yuan")
        else:
            rate = proc_info["rate"]
            machining_cost = self.base_hourly_rate * rate * machining_hours * prec_coef * rough_coef
            chain.add_calculation("Machining Cost (M15)",
                                 f"BaseRate({self.base_hourly_rate}) * ProcessRate({rate}) * Hours({machining_hours}) * Precision({prec_coef}) * Roughness({rough_coef})",
                                 machining_cost, "yuan",
                                 {"formula": "Excel M15 = base_rate * proc_rate * hours * prec * rough"})

        chain.add_feature("machining_hours", machining_hours)
        chain.add_feature("process_rate", proc_info["rate"])
        chain.add_feature("precision_coef", prec_coef)

        # Step 6: Surface cost (L20)
        pricing_mode = params.get("pricing_mode", "by_quantity")
        surface_cost = 0.0
        if surface_key and surface_key in self.surface_rates:
            info = self.surface_rates[surface_key]
            if pricing_mode == "by_weight":
                surface_cost = weight_kg * info["by_weight"]
                chain.add_calculation("Surface Cost (L20)",
                                     f"Weight({weight_kg:.3f}kg) * Rate({info['by_weight']}yuan/kg)",
                                     surface_cost, "yuan")
            else:
                surface_cost = info["by_quantity"] * quantity
                chain.add_calculation("Surface Cost (L20)",
                                     f"PerPiece({info['by_quantity']}yuan) * Qty({quantity})",
                                     surface_cost, "yuan")
        else:
            chain.add_inference("No surface treatment", "Surface cost = 0", 1.0)

        # Step 7: Extra fees (L24)
        measurement_type = params.get("measurement", "标准")
        jig_fee = float(params.get("jig_fee") or 0)
        tool_fee = float(params.get("tool_fee") or 0)
        other_fee = float(params.get("other_fee") or 0)
        measurement_fee = self.measurement_rates.get(measurement_type, 0)
        extra_fees = measurement_fee + jig_fee + tool_fee + other_fee
        chain.add_calculation("Extra Fees (L24)",
                             f"Measurement({measurement_fee}) + Jig({jig_fee}) + Tool({tool_fee}) + Other({other_fee})",
                             extra_fees, "yuan")

        # Step 8: Final price (N27)
        profit_rate = float(params.get("profit_rate") or 0.30)
        discount = float(params.get("discount") or 1.0)
        total_cost = extra_fees + machining_cost + material_cost + surface_cost

        if profit_rate >= 1:
            final_price = total_cost * 10
        else:
            final_price = total_cost / (1 - profit_rate) * discount

        unit_price = final_price / quantity if quantity > 0 else final_price
        profit = final_price - total_cost
        lead_time = max(2, int(machining_hours * quantity / 8) + 2)

        chain.add_calculation("Total Cost",
                             f"Extra({extra_fees}) + Machining({machining_cost:.2f}) + Material({material_cost:.2f}) + Surface({surface_cost:.2f})",
                             total_cost, "yuan", {"formula": "Excel SUM(L24,M15,O6,L20)"})

        chain.add_calculation("Final Price (N27)",
                             f"TotalCost({total_cost:.2f}) / (1 - ProfitRate({profit_rate})) * Discount({discount})",
                             final_price, "yuan",
                             {"formula": "Excel N27 = SUM/(1-H27)*L27"})

        # Step 9: Profit analysis
        profit_margin = (profit / final_price * 100) if final_price > 0 else 0
        chain.add_feature("profit_margin", f"{profit_margin:.1f}%")
        chain.add_feature("lead_time", f"{lead_time} days")

        if profit_margin < 5:
            chain.add_warning(f"Low profit margin ({profit_margin:.1f}%) - consider rejecting", "critical")
        elif profit_margin < 10:
            chain.add_warning(f"Thin profit margin ({profit_margin:.1f}%) - negotiate price", "warning")

        # Step 10: Conclusion
        chain.add_conclusion(
            f"Quote: {mat_info['name']} x{quantity} = {final_price:.2f}yuan",
            confidence=0.95,
            rationale=f"Material={mat_info['name']}, Process={process}, Surface={surface_key or 'none'}, "
                     f"Weight={weight_kg:.3f}kg, Hours={machining_hours:.1f}h, Profit={profit_margin:.1f}%",
            recommendations=[f"Unit price: {unit_price:.2f}yuan/piece", f"Lead time: {lead_time} days"]
        )

        result = {
            "material": mat_info["name"],
            "material_code": material,
            "surface": surface_key or "无",
            "quantity": quantity,
            "process": process,
            "tolerance": tolerance,
            "shape": shape,
            "weight_kg": round(weight_kg, 4),
            "material_cost": round(material_cost, 2),
            "machining_cost": round(machining_cost, 2),
            "surface_cost": round(surface_cost, 2),
            "extra_fees": round(extra_fees, 2),
            "total_cost": round(total_cost, 2),
            "total_price": round(final_price, 2),  # 小计 = 单价×数量 = 总价
            "unit_price": round(unit_price, 2),
            "profit": round(profit, 2),
            "final_price": round(final_price, 2),
            "profit_rate": profit_rate,
            "discount": discount,
            "machine_hours": round(machining_hours, 2),
            "hourly_rate": round(self.base_hourly_rate * proc_info["rate"], 2) if proc_info["unit"] != "length" else 0,
            "tol_coef": prec_coef,
            "batch_discount": discount,
            "lead_time_days": lead_time,
            "pricing_mode": pricing_mode,
            "measurement": measurement_type,
            "measurement_fee": measurement_fee,
            "jig_fee": jig_fee,
            "tool_fee": tool_fee,
            "engine": "quote-v3.0 (Excel还原)",
            "reasoning_chain": chain.finish().to_dict(),
            "reasoning_chain_id": register_chain(chain),
        }
        return result

    def estimate_machining_hours(self, weight_kg, process, shape="flat", tolerance="IT8"):
        """估算加工时间 - 基于行业经验: 
        CNC加工时间主要取决于零件复杂度和尺寸
        简单件0.5-1h, 中等1-3h, 复杂3-8h
        """
        # 基于重量的基础时间估算 (参考真实CNC工时)
        # 0.1kg ~ 0.5h, 0.5kg ~ 1.5h, 1kg ~ 3h, 2kg ~ 5h, 5kg ~ 8h
        import math
        base_time = 0.5 + 2.5 * math.log(1 + weight_kg * 5) / math.log(10)
        
        # 形状系数（统一：flange/sleeve/bracket 加入字典）
        sf = {"flat": 1.0, "round": 0.8, "pipe": 1.2, "box": 1.5, "square": 1.3,
              "complex": 2.0, "flange": 1.1, "disc": 1.1, "sleeve": 0.9,
              "bushing": 0.9, "bracket": 1.4, "l": 1.4}
        shape_factor = sf.get(shape.lower(), 1.0)
        
        # 精度系数
        tf = 1.0
        if tolerance in ("IT4", "IT5"): tf = 1.8
        elif tolerance == "IT6": tf = 1.5
        elif tolerance == "IT7": tf = 1.3
        elif tolerance == "IT8": tf = 1.0
        elif tolerance == "IT9": tf = 0.9
        
        # 工艺系数
        pf = 1.3 if process in ("五轴CNC", "四轴CNC") else 1.0
        
        result = base_time * shape_factor * tf * pf
        return max(0.3, min(12.0, round(result, 1)))

    def extract_params_from_message(self, message):
        """从消息中提取报价参数（健壮版）

        支持:
          - 材料: 6061/7075/304/45钢/黄铜/ABS...
          - 数量: N件/个/台/批
          - 尺寸: 直径/外径/内径/长/宽/高/厚, 100x80x20, Φ50
          - 形状: 法兰/轴套/轴/平板/箱体/支架
          - 表面处理: 阳极氧化/镀镍/发黑/喷砂...
          - 公差/精度: IT4~IT10, Ra0.4...
          - 孔特征: 4个M8孔

        返回 dict 带 _sources 字段记录每个参数来源。
        """
        import re
        params = {}
        sources = {}
        msg = message.lower()
        msg_orig = message

        # 1. 材料
        material = None
        for alias, mat in self.material_aliases.items():
            if alias.lower() in msg:
                material = mat
                break
        # 精确材料名匹配
        if not material:
            for key in self.materials:
                if key.lower() in msg:
                    material = key
                    break
        if material:
            params["material"] = material
            sources["material"] = "消息"

        # 2. 数量
        qty_match = re.search(r"(\d+)\s*(?:件|个|台|批|pcs|pieces?)", msg)
        if qty_match:
            params["quantity"] = int(qty_match.group(1))
            sources["quantity"] = "消息"

        # 3. 形状 (用于重量估算)
        shape_map = {
            "法兰": "flange", "法兰盖": "flange", "闷盖": "flange",
            "检查盖": "flange", "圆盘": "flange", "盘": "flange",
            "轴套": "sleeve", "衬套": "sleeve",
            "光轴": "round", "轴": "round", "齿轮轴": "round",
            "圆柱": "round",
            "平板": "flat", "板": "flat", "垫板": "flat",
            "箱体": "box", "方块": "box", "壳体": "box", "盒子": "box",
            "支架": "bracket", "l型支架": "bracket",
            "管": "pipe", "圆管": "pipe", "pipe": "pipe",
        }
        for cn, en in shape_map.items():
            if cn in msg:
                params["shape"] = en
                sources["shape"] = "消息"
                break

        # 4. 尺寸解析
        dimensions = {}
        # 直径/外径 Φ120 / 直径120 / D120 / od120
        d_match = (re.search(r'[ΦφDd]\s*(\d+(?:\.\d+)?)', msg_orig) or
                   re.search(r'(?:直径|外径|od)\s*(\d+(?:\.\d+)?)', msg))
        if d_match:
            dimensions["D"] = float(d_match.group(1))
        # 内径 id / 内孔 / 内径50
        id_match = re.search(r'(?:内径|内孔|id)\s*(\d+(?:\.\d+)?)', msg)
        if id_match:
            dimensions["d"] = float(id_match.group(1))
        # 长/高/长度 L/length/h/高
        l_match = re.search(r'(?:长|长度|高|h|l|length)\s*(\d+(?:\.\d+)?)', msg)
        if l_match:
            dimensions["L"] = float(l_match.group(1))
        # 宽 w/width/宽
        w_match = re.search(r'(?:宽|w|width)\s*(\d+(?:\.\d+)?)', msg)
        if w_match:
            dimensions["W"] = float(w_match.group(1))
        # 厚/厚度 t/thickness
        t_match = re.search(r'(?:厚|厚度|t|thickness)\s*(\d+(?:\.\d+)?)', msg)
        if t_match:
            dimensions["H"] = float(t_match.group(1))
        # 100x80x20 / 100*80*20 / 100×80×20 (最多3个)
        dim3_match = re.search(r'(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)', msg)
        if dim3_match:
            # 平板类: 长x宽x厚; 箱体: 长x宽x高
            dimensions["L"] = float(dim3_match.group(1))
            dimensions["W"] = float(dim3_match.group(2))
            dimensions["H"] = float(dim3_match.group(3))
        else:
            # 100x80 (2个) → 平板/圆柱 默认厚度/高
            dim2_match = re.search(r'(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)', msg)
            if dim2_match and not dimensions.get("D"):
                dimensions["L"] = float(dim2_match.group(1))
                dimensions["W"] = float(dim2_match.group(2))

        if dimensions:
            params["dimensions"] = dimensions
            sources["dimensions"] = "消息"

        # 5. 表面处理（含子串/别名匹配）
        surface = None
        for alias, skey in self.surface_aliases.items():
            if alias.lower() in msg:
                surface = skey
                break
        if not surface:
            for skey in self.surface_rates:
                if skey.lower() in msg:
                    surface = skey
                    break
        if not surface:
            surface = self.resolve_surface(msg_orig)
        if surface:
            params["surface_treatment"] = surface
            sources["surface_treatment"] = "消息"

        # 6. 公差/精度
        tol_match = re.search(r'it(\d+)', msg)
        if tol_match:
            params["tolerance"] = f"IT{tol_match.group(1).upper()}"
            sources["tolerance"] = "消息"
        prec_match = re.search(r'ra\s*(0\.4|0\.8|1\.6|3\.2)', msg)
        if prec_match:
            params["roughness"] = f"Ra {prec_match.group(1)}"
            sources["roughness"] = "消息"

        # 7. 孔特征 (用于法兰)
        hole_match = re.search(r'(\d+)\s*[个只]\s*[mM]?(\d+(?:\.\d+)?)\s*(?:安装孔|螺栓孔|光孔|孔)', msg)
        if hole_match:
            params["bolt_holes"] = int(hole_match.group(1))
            params["bolt_d"] = float(hole_match.group(2))
            sources["bolt_holes"] = "消息"
            sources["bolt_d"] = "消息"
        else:
            mhole_match = re.search(r'[mM](\d+(?:\.\d+)?)\s*[x×]\s*(\d+)\s*(?:孔|个)', msg)
            if mhole_match:
                params["bolt_d"] = float(mhole_match.group(1))
                params["bolt_holes"] = int(mhole_match.group(2))
                sources["bolt_holes"] = "消息"
                sources["bolt_d"] = "消息"

        params["_sources"] = sources
        return params

    def merge_quote_params(self, message_params: dict, form_params: dict, defaults: dict = None) -> dict:
        """报价参数合并: 消息 > 表单 > 默认, 来源透明化

        返回 merged dict 带 _sources 字段。
        """
        defaults = defaults or {
            "material": "AL6061",
            "quantity": 10,
            "surface_treatment": "无",
            "tolerance": "IT8",
            "process": "三轴CNC",
            "shape": "flat",
            "precision": "2768-M&F",
            "roughness": "Ra1.6&Ra3.2",
            "pricing_mode": "by_quantity",
            "measurement": "标准",
            "profit_rate": 0.30,
            "discount": 1.0,
        }
        merged = dict(defaults)
        sources = {k: "默认" for k in defaults}

        # 表单优先于默认
        for k, v in form_params.items():
            if v is not None and v != '':
                merged[k] = v
                sources[k] = "表单"

        # 消息最优先 (但忽略 None/空值)
        msg_sources = message_params.pop("_sources", {})
        for k, v in message_params.items():
            if v is not None and v != '':
                merged[k] = v
                sources[k] = msg_sources.get(k, "消息")

        merged["_sources"] = sources
        return merged

    def calc_weight_by_density(self, volume_cm3: float, material_code: str) -> float:
        """按材料密度计算重量 (g)"""
        mat_info = self.materials.get(material_code, {"density": 2.8})
        return volume_cm3 * mat_info["density"]


_quote_adapter = None

def get_quote_adapter():
    global _quote_adapter
    if _quote_adapter is None:
        _quote_adapter = QuoteAdapter()
    return _quote_adapter
