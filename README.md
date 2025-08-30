# mem-eval

一个可运行示例，用于对比**Fat**(一次性返回超大数据)与**Paged**（分页搜索+增量记忆）两种策略对“记忆复用与延迟”的影响

```
python runners/run_letta.py \
  --mode fat \
  --out logs_letta_fat.jsonl \
  --n_facts 10000 \
  --seed 42
```
```
python runners/run_letta.py \
  --mode paged \
  --pages 3 \
  --page_size 50 \
  --out logs_letta_paged.jsonl \
  --n_facts 10000 \
  --seed 42
```
```
python analyse_logs.py logs_letta.jsonl
```