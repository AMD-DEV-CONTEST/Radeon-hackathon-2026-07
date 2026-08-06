# app/predictor.py - 重构后的代码

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union,Any
from datetime import datetime, timedelta
from .config import DEVICE, PREDICT_CONFIG, MODELS_DIR, LLM_CONFIG 
from .utils import  get_last_date,generate_future_daily_dates
from .config import (
    AGENT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT_EXTENDED,
    MEMORY_CONFIG, MODELS_DIR, MILVUS_CONFIG
)

class TimeSeriesTransformer(nn.Module):
    """时间序列预测Transformer模型"""
    
    def __init__(
        self,
        input_size: int = 5,
        d_model: int = 128,
        nhead: int = 8,
        num_layers: int = 4,
        seq_length: int = 60,
        pred_length: int = 20,
        dropout: float = 0.1
    ):
        super().__init__()
        
        self.input_size = input_size
        self.d_model = d_model
        self.seq_length = seq_length
        self.pred_length = pred_length
        
        # 特征投影
        self.input_proj = nn.Linear(input_size, d_model)
        
        # 位置编码
        self.pos_encoder = PositionalEncoding(d_model, dropout)
        
        # Transformer编码器
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        # 输出层
        self.output_proj = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, pred_length * input_size)
        )
        
        self._init_weights()
    
    def _init_weights(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)
    
    def forward(self, x):
        # x: [batch, seq, features]
        x = self.input_proj(x)
        x = self.pos_encoder(x)
        x = self.transformer(x)
        x = x[:, -1, :]  # 取最后时间步
        x = self.output_proj(x)
        x = x.view(-1, self.pred_length, self.input_size)
        return x


class LSTMPredictor(nn.Module):
    """LSTM 时间序列预测模型 - 作为第二种预测模型"""
    
    def __init__(
        self,
        input_size: int = 5,
        hidden_size: int = 128,
        num_layers: int = 2,
        seq_length: int = 60,
        pred_length: int = 20,
        dropout: float = 0.1
    ):
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.seq_length = seq_length
        self.pred_length = pred_length
        
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout
        )
        
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, pred_length * input_size)
        )
    
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last_output = lstm_out[:, -1, :]
        output = self.fc(last_output)
        output = output.view(-1, self.pred_length, self.input_size)
        return output


class LSTMConfig:
    def __init__(self, input_size=5, hidden_size=64, num_layers=2, seq_length=60, pred_length=20, dropout=0.1):
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.seq_length = seq_length
        self.pred_length = pred_length
        self.dropout = dropout


class LightLSTMPredictor(nn.Module):
    """轻量级LSTM预测模型 - 充分利用GPU算力"""
    
    def __init__(self, config: LSTMConfig):
        super().__init__()
        self.config = config
        self.seq_length = config.seq_length
        self.pred_length = config.pred_length
        
        self.lstm = nn.LSTM(
            input_size=config.input_size,
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            batch_first=True,
            dropout=config.dropout if config.num_layers > 1 else 0
        )
        
        self.fc = nn.Sequential(
            nn.Linear(config.hidden_size, config.hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_size // 2, config.pred_length * config.input_size)
        )
    
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last_output = lstm_out[:, -1, :]
        output = self.fc(last_output)
        output = output.view(-1, self.pred_length, self.config.input_size)
        return output


class TransformerLightConfig:
    def __init__(self, input_size=5, d_model=64, nhead=4, num_layers=2, seq_length=60, pred_length=20, dropout=0.1):
        self.input_size = input_size
        self.d_model = d_model
        self.nhead = nhead
        self.num_layers = num_layers
        self.seq_length = seq_length
        self.pred_length = pred_length
        self.dropout = dropout


class LightTransformerPredictor(nn.Module):
    """轻量级Transformer预测模型 - 充分利用GPU算力"""
    
    def __init__(self, config: TransformerLightConfig):
        super().__init__()
        self.config = config
        self.seq_length = config.seq_length
        self.pred_length = config.pred_length
        
        self.input_proj = nn.Linear(config.input_size, config.d_model)
        self.pos_encoder = PositionalEncoding(config.d_model, config.dropout)
        
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.nhead,
            dim_feedforward=config.d_model * 4,
            dropout=config.dropout,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=config.num_layers)
        
        self.output_proj = nn.Sequential(
            nn.Linear(config.d_model, config.d_model // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.d_model // 2, config.pred_length * config.input_size)
        )
    
    def forward(self, x):
        x = self.input_proj(x)
        x = self.pos_encoder(x)
        x = self.transformer(x)
        x = x[:, -1, :]
        x = self.output_proj(x)
        x = x.view(-1, self.pred_length, self.config.input_size)
        return x


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, dropout=0.1, max_len=5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.register_buffer('pe', pe)
    
    def forward(self, x):
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


class ETFPricePredictor:
    """ETF价格预测器"""
    
    def __init__(self, base_model_name: Optional[str] = None):
        if base_model_name is None:
            base_model_name = LLM_CONFIG.get("model_name", "Qwen/mapfinben-qwen35-9b")
        self.base_model_name = base_model_name

        self.model = TimeSeriesTransformer(
            seq_length=PREDICT_CONFIG["seq_length"],
            pred_length=PREDICT_CONFIG["pred_length"]
        ).to(DEVICE)
        
        self.lstm_model = LSTMPredictor(
            seq_length=PREDICT_CONFIG["seq_length"],
            pred_length=PREDICT_CONFIG["pred_length"]
        ).to(DEVICE)

        self.model_path = PREDICT_CONFIG["model_path"]
        self.lstm_model_path = MODELS_DIR / "etf_predictor_lstm.pt"
        self.seq_length = PREDICT_CONFIG["seq_length"]
        self.pred_length = PREDICT_CONFIG["pred_length"]
        self.lora_path = PREDICT_CONFIG.get("lora_path", MODELS_DIR / "lora_etf_advisor")
        self.norm_params = {}
        self.is_trained = False
        
        # 尝试加载预训练模型
        if self.model_path.exists():
            self.load_model()
    
        if self.lstm_model_path.exists():
            self.load_lstm_model()

    
        self._init_gpu_predictors()
    
    def _init_gpu_predictors(self):
        """初始化GPU本地预测器（无需预训练）"""
        from .config import GPU_LOCAL_PREDICTORS, DEVICE
        
        self.gpu_predictors = {}
        
        # 初始化LSTM预测器
        if GPU_LOCAL_PREDICTORS.get("lstm_light", {}).get("enabled", True):
            config = GPU_LOCAL_PREDICTORS["lstm_light"]
            self.gpu_predictors["lstm_light"] = {
                "model": LightLSTMPredictor(
                    LSTMConfig(
                        hidden_size=config.get("hidden_size", 64),
                        num_layers=config.get("num_layers", 2),
                        dropout=config.get("dropout", 0.1)
                    )
                ).to(DEVICE),
                "config": config,
                "name": config.get("name", "LSTM-Light (GPU)")
            }
        
        # 初始化Transformer预测器
        if GPU_LOCAL_PREDICTORS.get("transformer_light", {}).get("enabled", True):
            config = GPU_LOCAL_PREDICTORS["transformer_light"]
            self.gpu_predictors["transformer_light"] = {
                "model": LightTransformerPredictor(
                    TransformerLightConfig(
                        d_model=config.get("d_model", 64),
                        nhead=config.get("nhead", 4),
                        num_layers=config.get("num_layers", 2),
                        dropout=config.get("dropout", 0.1)
                    )
                ).to(DEVICE),
                "config": config,
                "name": config.get("name", "Transformer-Light (GPU)")
            }
    
    def predict_gpu_local(self, df: pd.DataFrame) -> Dict:
        """使用GPU本地模型进行预测"""
        if len(df) < self.seq_length:
            return {'error': '数据不足', 'success': False}
        
        from .config import DEVICE
        
        features = df[['open', 'high', 'low', 'close', 'volume']].values.astype(np.float32)
        means = features.mean(axis=0)
        stds = features.std(axis=0)
        stds[stds == 0] = 1
        features_norm = (features - means) / stds
        
        data_tensor = torch.tensor(features_norm, dtype=torch.float32).unsqueeze(0).to(DEVICE)
        
        results = {}
        valid_predictions = []
        weights = []
        
        for key, predictor_info in self.gpu_predictors.items():
            model = predictor_info["model"]
            name = predictor_info["name"]
            weight = predictor_info["config"].get("weight", 0.3)
            
            try:
                model.eval()
                with torch.no_grad():
                    pred = model(data_tensor)
                
                pred_np = pred.cpu().numpy()[0]
                pred_denorm = pred_np * stds + means
                
                close_prices = pred_denorm[:, 3]
                
                # 使用修复后的日期生成函数
                last_date = get_last_date(df)
                future_dates =  generate_future_daily_dates(last_date, len(close_prices))
                
                results[name] = {
                    'success': True,
                    'model': name,
                    'dates': future_dates,
                    'close': close_prices.tolist(),
                    'predicted_change': (close_prices[-1] - close_prices[0]) / close_prices[0],
                    'confidence': 0.5,
                    'is_gpu_local': True,
                    'latest_date': last_date.strftime('%Y/%m/%d')
                }
                valid_predictions.append(results[name])
                weights.append(weight)
            except Exception as e:
                results[name] = {'error': str(e), 'success': False}
        
        if valid_predictions:
            total_weight = sum(weights)
            normalized_weights = [w / total_weight for w in weights]
            
            ensemble_close = np.zeros(len(valid_predictions[0]['close']))
            for pred, w in zip(valid_predictions, normalized_weights):
                ensemble_close += np.array(pred['close']) * w
            
            last_date = get_last_date(df)
            future_dates =  generate_future_daily_dates(last_date, len(ensemble_close))
            
            results['ensemble'] = {
                'success': True,
                'dates': future_dates,
                'close': ensemble_close.tolist(),
                'predicted_change': (ensemble_close[-1] - ensemble_close[0]) / ensemble_close[0],
                'confidence': 0.6,
                'model_weights': {pred.get('model', 'Unknown'): w 
                                 for pred, w in zip(valid_predictions, normalized_weights)},
                'is_ensemble': True,
                'latest_date': last_date.strftime('%Y/%m/%d')
            }
        
        return results

    
#     async def call_llm_api(self, df: pd.DataFrame, llm_type: str = 'deepseek') -> Dict:
#         """调用大模型API进行预测"""
#         from .config import LLM_API_CONFIG
#         import httpx
        
#         config = LLM_API_CONFIG.get(llm_type)
#         if not config or not config.get('enabled', False):
#             return {'error': f'LLM {llm_type} 未启用', 'success': False}
        
#         # 准备数据摘要
#         data_summary = {
#             'last_price': float(df['close'].iloc[-1]),
#             'ma5': float(df['close'].rolling(5).mean().iloc[-1]),
#             'ma20': float(df['close'].rolling(20).mean().iloc[-1]),
#             'volatility': float(df['close'].pct_change().std() * np.sqrt(252))
#         }
        
#         data_str = self.convert_stock_data(df)
#         prompt = f"""基于以下股票基金数据预测未来20天价格走势：
#         5日均线: {data_summary['ma5']:.3f}
#         20日均线: {data_summary['ma20']:.3f}
#         年化波动率: {data_summary['volatility']:.3f}
        
# 【每日数据】
# {data_str}
#         请输出未来20天的预测价格。
#         ## 按如下格式输出JSON
# ```json
# {{
#     "stocks": {{
#         "SYMBOL": {{
#             "latest_date": "YYYY-MM-DD",
#             "latest_close": 数字,
#             "1D": {{
#                 "forecast": {{"date":[], "open":[], "high":[], "low":[], "close":[], "volume":[], "amount":[]}},
#                 "accuracy_metrics": {{"mae":0, "rmse":0, "mape":0, "direction_accuracy":0, "max_error":0}},
#                 "analysis_summary": {{"predicted_trend":"", "expected_return":0, "confidence_level":"", "key_observations":"", "recommendation":"", "risk_warning":""}}
#             }}
           
#         }}
#     }}
# }}"""
#         system_prompt = AGENT_SYSTEM_PROMPT + "\n" + AGENT_SYSTEM_PROMPT_EXTENDED
#         messages = [{"role": "system", "content":system_prompt},{"role": "user", "content": prompt}]
        
#         try:
#             async with httpx.AsyncClient(timeout=30.0) as client:
#                 response = await client.post(
#                     config['api_base'],
#                     headers={
#                         "Authorization": f"Bearer {config['api_key']}",
#                         "Content-Type": "application/json"
#                     },
#                     json={
#                         "model": config['model'],
#                         "messages": messages,
#                         "temperature": 0.7
#                     }
#                 )
#                 result = response.json()
#                 content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                
#                 # 尝试解析JSON响应
#                 import re
#                 json_match = re.search(r'\[[\d.,\s]+\]', content)
#                 if json_match:
#                     import json
#                     pred_prices = json.loads(json_match.group())
#                     if len(pred_prices) >= 20:
#                         pred_prices = pred_prices[:20]
#                         pred_dates = [(df.index[-1] + timedelta(days=i+1)).strftime('%Y-%m-%d') 
#                                      for i in range(len(pred_prices))]
                        
#                         return {
#                             'success': True,
#                             'model': config['name'],
#                             'dates': pred_dates,
#                             'close': pred_prices,
#                             'predicted_change': (pred_prices[-1] - pred_prices[0]) / pred_prices[0],
#                             'confidence': 0.7,
#                             'is_llm': True,
#                             'raw_response': content
#                         }
                
#                 return {
#                     'success': True,
#                     'model': config['name'],
#                     'response': content,
#                     'is_llm': True,
#                     'raw_response': content
#                 }
#         except Exception as e:
#             return {'error': str(e), 'success': False}
    
    # def get_all_predictions(self, df: pd.DataFrame) -> Dict:
    #     """获取所有预测结果（GPU本地 + Transformer-LSTM）"""
    #     results = {
    #         'gpu_local': {},
    #         'transformer_lstm': {},
    #         'all_predictions': []
    #     }
        
    #     # 1. GPU本地预测
    #     gpu_results = self.predict_gpu_local(df)
    #     for name, pred in gpu_results.items():
    #         if pred.get('success', False):
    #             results['gpu_local'][name] = pred
    #             results['all_predictions'].append(pred)
        
    #     # 2. Transformer-LSTM预测
    #     try:
    #         trans_pred = self.predict(df, use_ensemble=True)
    #         if trans_pred.get('success', False):
    #             results['transformer_lstm'] = trans_pred
    #             results['all_predictions'].append(trans_pred)
    #     except Exception:
    #         pass
        
    #     # 3. ✅ Qwen 预测
    #     try:
    #         qwen_pred = self.call_llm(df, llm_type='qwen_local', use_full_data=True)
    #         if qwen_pred.get('success', False):
    #             results['qwen'] = qwen_pred
    #             results['all_predictions'].append(qwen_pred)
    #     except Exception as e:
    #         print(f"⚠️ Qwen 预测失败: {e}")
            
    #     # 4. 可选：远程 DeepSeek
    #     try:
    #         deepseek_pred = self.call_llm(df, llm_type='deepseek', use_full_data=False)
    #         if deepseek_pred.get('success', False):
    #             results['llm']['deepseek'] = deepseek_pred
    #             results['all_predictions'].append(deepseek_pred)
    #     except Exception as e:
    #         print(f"⚠️ DeepSeek 预测失败: {e}")
            
    #     return results
    
    def load_lstm_model(self):
        """加载 LSTM 模型"""
        try:
            checkpoint = torch.load(self.lstm_model_path, map_location=DEVICE)
            self.lstm_model.load_state_dict(checkpoint['model_state_dict'])
            print("LSTM 预测模型加载成功")
        except Exception as e:
            print(f"⚠️ LSTM 模型加载失败: {e}")

    def load_model(self):
        """加载模型"""
        try:
            checkpoint = torch.load(self.model_path, map_location=DEVICE)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.norm_params = checkpoint.get('norm_params', {})
            self.is_trained = True
            print("预测模型加载成功")
        except Exception as e:
            print(f"⚠️ 模型加载失败: {e}")
    
    def save_lstm_model(self):
        """保存 LSTM 模型"""
        checkpoint = {
            'model_state_dict': self.lstm_model.state_dict(),
            'norm_params': self.norm_params,
        }
        torch.save(checkpoint, self.lstm_model_path)
        print(f"LSTM 模型已保存: {self.lstm_model_path}")


    # ============================================================
    # 合并后的通用方法
    # ============================================================
        
    def _prepare_data_tensor(self, df: pd.DataFrame) -> torch.Tensor:
        """准备数据张量，自动截断过长序列"""
        # 获取特征数据
        features = df[['open', 'high', 'low', 'close', 'volume']].values.astype(np.float32)
        
       
        # ✅ 如果数据量超过 seq_length，只取最近的数据
        if len(features) > self.seq_length:
            features = features[-self.seq_length:]
        
        if np.isnan(features).any():
            # 使用前向填充处理 NaN
            features_df = pd.DataFrame(features)
            features_df = features_df.ffill().bfill().fillna(0)
            features = features_df.values
        
        # 检查无限值
        if np.isinf(features).any():
            features = np.where(np.isinf(features), 0, features)
        
        # 标准化
        means = features.mean(axis=0)
        stds = features.std(axis=0)
        stds[stds == 0] = 1
        features_norm = (features - means) / stds
 
        if np.isnan(features_norm).any():
            features_norm = np.nan_to_num(features_norm, nan=0.0)
       
        self.norm_params['means'] = means
        self.norm_params['stds'] = stds
        
        return torch.tensor(features_norm, dtype=torch.float32).unsqueeze(0)
    

    
    def _format_prediction_response(
        self,
        pred_denorm: np.ndarray,
        future_dates: List[datetime],
        df: pd.DataFrame,
        extra_data: Optional[Dict] = None
    ) -> Dict:
        """格式化预测响应"""
        close_prices = pred_denorm[:, 3]
        
        if np.isnan(close_prices).any():
            close_prices = np.nan_to_num(close_prices, nan=0.0)


        # 计算置信区间
        recent_vol = df['close'].pct_change().std() * np.sqrt(252)
        confidence = 1.96 * recent_vol * np.sqrt(self.pred_length / 252)
        
        # 获取最新日期
        latest_date = get_last_date(df)
        
        response = {
            'success': True,
            'dates': [d.strftime('%Y-%m-%d') for d in future_dates],
            'open': pred_denorm[:, 0].tolist(),
            'high': pred_denorm[:, 1].tolist(),
            'low': pred_denorm[:, 2].tolist(),
            'close': close_prices.tolist(),
            'confidence': confidence,
            'predicted_change': (close_prices[-1] - close_prices[0]) / close_prices[0],
            'latest_date': latest_date.strftime('%Y/%m/%d')
        }
        
        if extra_data:
            response.update(extra_data)
        
        return response
    
    def _run_single_model_prediction(self, model: nn.Module, data_tensor: torch.Tensor) -> np.ndarray:
        """运行单个模型预测"""
        model.eval()
        with torch.no_grad():
            pred = model(data_tensor)
        return pred.cpu().numpy()[0]
    
    def _denormalize_predictions(self, pred_np: np.ndarray) -> np.ndarray:
        """反标准化预测结果"""
        means = self.norm_params['means']
        stds = self.norm_params['stds']
        return pred_np * stds + means
    
    def predict_ensemble(self, df: pd.DataFrame) -> Dict:
        """双模型集成预测"""
        if len(df) < self.seq_length:
            return {
                'error': f'数据不足，需要至少{self.seq_length}个交易日',
                'success': False
            }
        
        # 准备数据
        data_tensor = self._prepare_data_tensor(df)
        data_tensor = data_tensor.to(DEVICE)
        
        # 1. Transformer 预测
        pred_trans_np = self._run_single_model_prediction(self.transformer_model, data_tensor)
        
        # 2. LSTM 预测
        pred_lstm_np = self._run_single_model_prediction(self.lstm_model, data_tensor)
        
        # 3. 反标准化
        pred_trans_denorm = self._denormalize_predictions(pred_trans_np)
        pred_lstm_denorm = self._denormalize_predictions(pred_lstm_np)
        
        # 4. 集成预测（加权平均，Transformer 权重 0.6，LSTM 权重 0.4）
        ensemble_weight = 0.6
        pred_ensemble = pred_trans_denorm * ensemble_weight + pred_lstm_denorm * (1 - ensemble_weight)
        
        # 5. 生成日期
        last_date = df.index[-1]
        future_dates = generate_future_daily_dates(last_date, self.pred_length)
        
        # 6. 格式化响应
        return self._format_prediction_response(
            pred_ensemble,
            future_dates,
            df,
            extra_data={
                'transformer_prediction': {
                    'close': pred_trans_denorm[:, 3].tolist(),
                    'change': (pred_trans_denorm[-1, 3] - pred_trans_denorm[0, 3]) / pred_trans_denorm[0, 3]
                },
                'lstm_prediction': {
                    'close': pred_lstm_denorm[:, 3].tolist(),
                    'change': (pred_lstm_denorm[-1, 3] - pred_lstm_denorm[0, 3]) / pred_lstm_denorm[0, 3]
                },
                'ensemble_weight': ensemble_weight
            }
        )
    
    def predict_single(self, df: pd.DataFrame) -> Dict:
        """单个模型预测"""
        if len(df) < self.seq_length:
            return {
                'error': f'数据不足，需要至少{self.seq_length}个交易日',
                'success': False
            }
        
        # 准备数据
        data_tensor = self._prepare_data_tensor(df)
        model_dtype = next(self.model.parameters()).dtype
        data_tensor = data_tensor.to(DEVICE).to(model_dtype)
        
        # 预测
        pred_np = self._run_single_model_prediction(self.model, data_tensor)
        
        # 反标准化
        pred_denorm = self._denormalize_predictions(pred_np)
        
        # 生成日期
        last_date = df.index[-1]
        future_dates = generate_future_daily_dates(last_date, self.pred_length)
        
        # 格式化响应
        return self._format_prediction_response(pred_denorm, future_dates, df)

            
    def save_model(self):
        """保存模型"""
        checkpoint = {
            'model_state_dict': self.model.state_dict(),
            'norm_params': self.norm_params,
        }
        torch.save(checkpoint, self.model_path)
        print(f"模型已保存: {self.model_path}")
    
    def prepare_data(self, df: pd.DataFrame) -> torch.Tensor:
        """准备输入数据（保留兼容性）"""
        return self._prepare_data_tensor(df)
    
    def predict(self, df: pd.DataFrame, use_ensemble: bool = True) -> Dict:
        """预测未来价格（默认使用双模型集成）"""
        if use_ensemble and self.lstm_model_path.exists():
            result = self.predict_ensemble(df)
        else:
            result = self.predict_single(df)
        
        # 确保 latest_date 存在
        if result.get('success', False) and 'latest_date' not in result:
            if hasattr(df.index[-1], 'strftime'):
                result['latest_date'] = df.index[-1].strftime('%Y-%m-%d')
            else:
                result['latest_date'] = str(df.index[-1])
        
        return result
    
    def train_lstm(self, df_list: List[pd.DataFrame], epochs: int = 50) -> Dict:
        """训练 LSTM 模型"""
        sequences = []
        targets = []
        
        for df in df_list:
            if len(df) < self.seq_length + self.pred_length:
                continue
            
            data = df[['open', 'high', 'low', 'close', 'volume']].values.astype(np.float32)
            means = data.mean(axis=0)
            stds = data.std(axis=0)
            stds[stds == 0] = 1
            data_norm = (data - means) / stds
            
            for i in range(len(data_norm) - self.seq_length - self.pred_length + 1):
                sequences.append(data_norm[i:i+self.seq_length])
                targets.append(data_norm[i+self.seq_length:i+self.seq_length+self.pred_length])
        
        if not sequences:
            return {'error': '数据不足', 'success': False}
        
        X = torch.tensor(np.array(sequences), dtype=torch.float32).to(DEVICE)
        y = torch.tensor(np.array(targets), dtype=torch.float32).to(DEVICE)
        
        dataset = torch.utils.data.TensorDataset(X, y)
        dataloader = torch.utils.data.DataLoader(dataset, batch_size=32, shuffle=True)
        
        optimizer = torch.optim.Adam(self.lstm_model.parameters(), lr=0.001)
        criterion = nn.HuberLoss()
        
        self.lstm_model.train()
        losses = []
        
        for epoch in range(epochs):
            epoch_loss = 0
            for batch_x, batch_y in dataloader:
                optimizer.zero_grad()
                pred = self.lstm_model(batch_x)
                loss = criterion(pred, batch_y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.lstm_model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()
            
            avg_loss = epoch_loss / len(dataloader)
            losses.append(avg_loss)
        
        self.save_lstm_model()
        
        return {
            'success': True,
            'losses': losses,
            'n_samples': len(sequences),
            'final_loss': losses[-1]
        }
        
    def train(self, df_list: List[pd.DataFrame], epochs: int = 50) -> Dict:
        """训练模型"""
        sequences = []
        targets = []
        
        for df in df_list:
            if len(df) < self.seq_length + self.pred_length:
                continue
            
            data = df[['open', 'high', 'low', 'close', 'volume']].values.astype(np.float32)
            means = data.mean(axis=0)
            stds = data.std(axis=0)
            stds[stds == 0] = 1
            data_norm = (data - means) / stds
            
            for i in range(len(data_norm) - self.seq_length - self.pred_length + 1):
                sequences.append(data_norm[i:i+self.seq_length])
                targets.append(data_norm[i+self.seq_length:i+self.seq_length+self.pred_length])
        
        if not sequences:
            return {'error': '数据不足', 'success': False}
        
        X = torch.tensor(np.array(sequences), dtype=torch.float32).to(DEVICE)
        y = torch.tensor(np.array(targets), dtype=torch.float32).to(DEVICE)
        
        dataset = torch.utils.data.TensorDataset(X, y)
        dataloader = torch.utils.data.DataLoader(
            dataset, batch_size=32, shuffle=True
        )
        
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        criterion = nn.HuberLoss()
        
        self.model.train()
        losses = []
        
        for epoch in range(epochs):
            epoch_loss = 0
            for batch_x, batch_y in dataloader:
                optimizer.zero_grad()
                pred = self.model(batch_x)
                loss = criterion(pred, batch_y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()
            
            avg_loss = epoch_loss / len(dataloader)
            losses.append(avg_loss)
        
        self.is_trained = True
        self.save_model()
        
        return {
            'success': True,
            'losses': losses,
            'n_samples': len(sequences),
            'final_loss': losses[-1]
        }
        

    # def convert_stock_data(self, symbol, df, days: int = 90) -> Dict:
    #     """将ETF数据转换为CSV字符串格式"""
    #     csv_string=""
    #     try:
    #         if df is None or df.empty:
    #             return csv_string
            
    #         # 数据预处理
    #         # df['date'] = pd.to_datetime(df['date'])
    #         df.loc[:, 'date'] = pd.to_datetime(df['date'])
    #         df = df.set_index('date')
    #         df = df.ffill().bfill()
    #         df = df.tail(days)
            
    #         # ✅ 转换为CSV字符串(省Token)
    #         csv_string = df[['open', 'high', 'low', 'close', 'volume','amount']].round(4).to_csv(
    #             header=False, 
    #             float_format='%.4f',
    #             date_format='%Y-%m-%d'
    #         )

    #     except Exception as e:
    #         print(f"❌ 获取 {symbol} 数据失败: {e}")
        
    #     return csv_string
    
    
#     def call_qwen(self, df: pd.DataFrame) -> Dict:
#         """调用本地 Qwen 模型进行预测"""
#         try:
#             from .llm_client import get_llm_client
            
#             llm = get_llm_client()
            
#             if len(df) < 30:
#                 return {
#                     'success': False,
#                     'error': f'数据不足，需要至少 30 个交易日，当前只有 {len(df)} 个',
#                     'is_qwen': True
#                 }
            
#             # 准备数据
#             n_days = min(100, len(df))
#             recent_df = df.tail(n_days).copy()
            
#             # 重置索引获取日期列
#             if recent_df.index.name is None:
#                 recent_df = recent_df.reset_index()
#                 recent_df.columns = ['date', 'open', 'high', 'low', 'close', 'volume'][:len(recent_df.columns)]
#             else:
#                 recent_df = recent_df.reset_index()
            
#             # 格式化数据
#             data_rows = []
#             for _, row in recent_df.iterrows():
#                 date_val = row[0] if isinstance(row[0], (pd.Timestamp, datetime, str)) else row['date']
#                 date_str = date_val.strftime('%Y-%m-%d') if hasattr(date_val, 'strftime') else str(date_val)
                
#                 open_val = row[1] if len(row) > 1 else row['open']
#                 high_val = row[2] if len(row) > 2 else row['high']
#                 low_val = row[3] if len(row) > 3 else row['low']
#                 close_val = row[4] if len(row) > 4 else row['close']
#                 volume_val = row[5] if len(row) > 5 else row['volume']
                
#                 data_rows.append(
#                     f"{date_str} | O:{open_val:.4f} H:{high_val:.4f} "
#                     f"L:{low_val:.4f} C:{close_val:.4f} V:{volume_val:.0f}"
#                 )
            
#             data_str = "\n".join(data_rows)
            
#             current_price = float(df['close'].iloc[-1])
#             price_high = float(df['high'].max())
#             price_low = float(df['low'].min())
            
#             prompt = f"""你是一个专业的 ETF 技术分析师。请基于以下最近 {len(recent_df)} 个交易日的每日 OHLCV 数据，分析技术指标并预测未来 20 个交易日的收盘价。

# 【数据统计】
# - 数据周期: {len(recent_df)} 个交易日
# - 当前价格: {current_price:.4f}
# - 期间最高: {price_high:.4f}
# - 期间最低: {price_low:.4f}

# 【每日数据】
# {data_str}

# 请分析技术指标（均线、RSI、MACD、布林带、成交量趋势等），然后预测未来 20 个交易日的收盘价。

# 最终输出格式：以 JSON 数组格式返回 20 个预测价格，例如：[3.85, 3.88, 3.92, ...]"""

#             response = llm.generate_response(
#                 messages=[{"role": "user", "content": prompt}],
#                 max_new_tokens=800,
#                 temperature=0.2,
#                 enable_thinking=False
#             )
            
#             # 解析 JSON 响应
#             import re
#             import json
            
#             json_match = re.search(r'\[[\d.,\s]+\]', response)
#             if json_match:
#                 try:
#                     pred_prices = json.loads(json_match.group())
#                     if len(pred_prices) >= 20:
#                         pred_prices = pred_prices[:20]
                        
#                         # 过滤异常值
#                         pred_prices = [p for p in pred_prices if p > 0 and p < current_price * 2.5]
#                         if len(pred_prices) >= 20:
#                             pred_prices = pred_prices[:20]
                            
#                             # ✅ 使用公共函数生成日期
#                             last_date = get_last_date(df)
#                             future_dates =  generate_future_daily_dates(last_date, len(pred_prices))
                            
#                             return {
#                                 'success': True,
#                                 'model': 'Qwen-Local',
#                                 'dates': future_dates,
#                                 'close': pred_prices,
#                                 'predicted_change': (pred_prices[-1] - pred_prices[0]) / pred_prices[0],
#                                 'confidence': 0.6,
#                                 'is_qwen': True,
#                                 'raw_response': response[:200] + "..." if len(response) > 200 else response
#                             }
#                 except:
#                     pass
            
#             return {
#                 'success': False,
#                 'error': '无法解析 Qwen 响应为有效的价格数组',
#                 'raw_response': response[:500] if response else '',
#                 'is_qwen': True
#             }
            
#         except Exception as e:
#             return {'error': str(e), 'success': False, 'is_qwen': True}

    # def _build_llm_prompt(self, df: pd.DataFrame, use_full_data: bool = True) -> str:
    #     """构建 LLM 提示词"""
    #     current_price = float(df['close'].iloc[-1])
        
    #     if use_full_data:
    #         n_days = min(100, len(df))
    #         recent_df = df.tail(n_days).copy()
            
    #         if recent_df.index.name is None:
    #             recent_df = recent_df.reset_index()
    #             recent_df.columns = ['date', 'open', 'high', 'low', 'close', 'volume'][:len(recent_df.columns)]
    #         else:
    #             recent_df = recent_df.reset_index()
            
    #         data_rows = []
    #         for _, row in recent_df.iterrows():
    #             date_val = row[0] if isinstance(row[0], (pd.Timestamp, datetime, str)) else row['date']
    #             date_str = date_val.strftime('%Y-%m-%d') if hasattr(date_val, 'strftime') else str(date_val)
                
    #             open_val = row[1] if len(row) > 1 else row['open']
    #             high_val = row[2] if len(row) > 2 else row['high']
    #             low_val = row[3] if len(row) > 3 else row['low']
    #             close_val = row[4] if len(row) > 4 else row['close']
    #             volume_val = row[5] if len(row) > 5 else row['volume']
                
    #             data_rows.append(
    #                 f"{date_str} | O:{open_val:.4f} H:{high_val:.4f} "
    #                 f"L:{low_val:.4f} C:{close_val:.4f} V:{volume_val:.0f}"
    #             )
            
    #         data_str = "\n".join(data_rows)
    #         price_high = float(df['high'].max())
    #         price_low = float(df['low'].min())
            
    #         return f"""你是一个专业的 ETF 技术分析师。请基于以下最近 {len(recent_df)} 个交易日的每日 OHLCV 数据，分析技术指标并预测未来 20 个交易日的收盘价。

    # 【数据统计】
    # - 数据周期: {len(recent_df)} 个交易日
    # - 当前价格: {current_price:.4f}
    # - 期间最高: {price_high:.4f}
    # - 期间最低: {price_low:.4f}

    # 【每日数据】
    # {data_str}

    # 请分析技术指标（均线、RSI、MACD、布林带、成交量趋势等），然后预测未来 20 个交易日的收盘价。

    # 最终输出格式：以 JSON 数组格式返回 20 个预测价格，例如：[3.85, 3.88, 3.92, ...]"""
    #     else:
    #         ma5 = float(df['close'].rolling(5).mean().iloc[-1])
    #         ma20 = float(df['close'].rolling(20).mean().iloc[-1])
    #         volatility = float(df['close'].pct_change().std() * np.sqrt(252))
            
    #         return f"""基于以下ETF数据预测未来20天价格走势：
    # 最新价格: {current_price:.3f}
    # 5日均线: {ma5:.3f}
    # 20日均线: {ma20:.3f}
    # 年化波动率: {volatility:.3f}

    # 请输出20天的预测价格（以JSON数组格式），只返回价格数组。"""

    # def _parse_llm_response(self, response: str, df: pd.DataFrame, model_name: str, is_local: bool = True) -> Dict:
    #     """解析 LLM 响应"""
    #     import re
    #     import json
        
    #     current_price = float(df['close'].iloc[-1])
        
    #     json_match = re.search(r'\[[\d.,\s]+\]', response)
    #     if json_match:
    #         try:
    #             pred_prices = json.loads(json_match.group())
    #             if len(pred_prices) >= 20:
    #                 pred_prices = pred_prices[:20]
    #                 pred_prices = [p for p in pred_prices if p > 0 and p < current_price * 2.5]
    #                 if len(pred_prices) >= 20:
    #                     pred_prices = pred_prices[:20]
                        
    #                     last_date = get_last_date(df)
    #                     future_dates =  generate_future_daily_dates(last_date, len(pred_prices))
                        
    #                     return {
    #                         'success': True,
    #                         'model': model_name,
    #                         'dates': future_dates,
    #                         'close': pred_prices,
    #                         'predicted_change': (pred_prices[-1] - pred_prices[0]) / pred_prices[0],
    #                         'confidence': 0.6,
    #                         'is_llm': True,
    #                         'is_local': is_local,
    #                         'raw_response': response[:200] + "..." if len(response) > 200 else response
    #                     }
    #         except:
    #             pass
        
    #     return {
    #         'success': False,
    #         'error': '无法解析 LLM 响应为有效的价格数组',
    #         'raw_response': response[:500] if response else '',
    #         'is_llm': True,
    #         'is_local': is_local
    #     }

    # def call_llm(
    #     self, 
    #     df: pd.DataFrame, 
    #     llm_type: str = 'qwen_local',
    #     use_full_data: bool = True
    # ) -> Dict:
    #     """
    #     调用 LLM 进行预测（统一接口）
        
    #     Args:
    #         df: 历史数据 DataFrame
    #         llm_type: LLM 类型 ('qwen_local', 'deepseek', 'openai')
    #         use_full_data: 是否使用完整历史数据（True=完整数据，False=摘要数据）
        
    #     Returns:
    #         预测结果字典
    #     """
    #     from .config import LLM_API_CONFIG
    #     import re
    #     import json
    #     import httpx
        
    #     try:
    #         # 1. 准备数据
    #         prompt = self._build_llm_prompt(df, use_full_data)
            
    #         # 2. 根据类型调用不同后端
    #         if llm_type == 'qwen_local':
    #             # 本地 Qwen 推理
    #             from .llm_client import get_llm_client
    #             llm = get_llm_client()
                
    #             response = llm.generate_response(
    #                 messages=[{"role": "user", "content": prompt}],
    #                 max_new_tokens=800,
    #                 temperature=0.2,
    #                 enable_thinking=False
    #             )
    #             model_name = 'Qwen-Local'
    #             is_llm = True
    #             is_local = True
                
    #         elif llm_type in ['deepseek', 'openai']:
    #             # 远程 API 调用
    #             config = LLM_API_CONFIG.get('external', {}).get(llm_type)
    #             if not config or not config.get('enabled', False):
    #                 return {'error': f'LLM {llm_type} 未启用', 'success': False}
                
    #             async def _call_remote():
    #                 async with httpx.AsyncClient(timeout=30.0) as client:
    #                     response = await client.post(
    #                         config['api_base'],
    #                         headers={
    #                             "Authorization": f"Bearer {config['api_key']}",
    #                             "Content-Type": "application/json"
    #                         },
    #                         json={
    #                             "model": config['model'],
    #                             "messages": [{"role": "user", "content": prompt}],
    #                             "temperature": 0.7
    #                         }
    #                     )
    #                     return response.json()
                
    #             try:
    #                 import asyncio
    #                 result = asyncio.run(_call_remote())
    #                 response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
    #                 model_name = config.get('name', llm_type)
    #                 is_llm = True
    #                 is_local = False
    #             except Exception as e:
    #                 return {'error': str(e), 'success': False}
    #         else:
    #             return {'error': f'不支持的 LLM 类型: {llm_type}', 'success': False}
            
    #         # 3. 解析响应（通用逻辑）
    #         return self._parse_llm_response(response, df, model_name, is_local)
            
    #     except Exception as e:
    #         return {'error': str(e), 'success': False}