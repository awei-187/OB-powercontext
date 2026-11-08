// Query-only lexical cleanup. Dense embeddings always retain the original question.
const stopwords=new Set('的 了 吗 呢 嘛 啊 我 我的 你 您 这个 那个 可以 能 还能 怎么办 怎么 怎样 如何 多少 多久 多长 时间 进行 一个 一下 刚 刚刚 会 被 到 再 却 没有 不能 可用 还有 相关 需要'.split(' '));
const segmenter=new Intl.Segmenter('zh-CN',{granularity:'word'});
export function lexicalQuery(query) {
  const terms=[...segmenter.segment(query.normalize('NFKC'))].filter(s=>s.isWordLike&&!stopwords.has(s.segment)).map(s=>s.segment);
  return [...new Set(terms)].join(' ') || query;
}
// Predeclared diagnostic variants. The baseline remains unchanged and executable.
export const variants=Object.freeze({
  'quality-v2':{candidates:50,clean:false,denseWeight:.75},
  'baseline-v1':{candidates:20,rankConstant:60,clean:false},
  'candidates-50':{candidates:50,rankConstant:60,clean:false},
  'rrf-10':{candidates:50,rankConstant:10,clean:false},
  'clean-rrf-60':{candidates:50,rankConstant:60,clean:true},
  'clean-rrf-10':{candidates:50,rankConstant:10,clean:true},
  'clean-score-75':{candidates:50,clean:true,denseWeight:.75},
  'score-75':{candidates:50,clean:false,denseWeight:.75},
  'score-50':{candidates:50,clean:false,denseWeight:.5},
  'score-90':{candidates:50,clean:false,denseWeight:.9},
});
export function defaultStrategy(collection) {
  return collection.schema?.fulltextIndex?.analyzer==='ik' && collection.schema.fulltextIndex.properties?.ik_mode==='max_word'?'quality-v2':'baseline-v1';
}
export function scoreFusionSql(table,config) {
  // Both candidate selection and score normalization/fusion execute inside seekdb.
  return `WITH dense AS (
    SELECT _id,document,metadata,cosine_distance(embedding, ?) AS distance
    FROM ${table} ORDER BY distance APPROXIMATE LIMIT ${config.candidates}
  ), lexical AS (
    SELECT _id,document,metadata,MATCH(document) AGAINST (? IN NATURAL LANGUAGE MODE) AS bm25
    FROM ${table} WHERE MATCH(document) AGAINST (? IN NATURAL LANGUAGE MODE)
    ORDER BY bm25 DESC,_id LIMIT ${config.candidates}
  ), normalized_dense AS (
    SELECT *,COALESCE((MAX(distance) OVER()-distance)/NULLIF(MAX(distance) OVER()-MIN(distance) OVER(),0),1) AS dense_score FROM dense
  ), normalized_lexical AS (
    SELECT *,bm25/NULLIF(MAX(bm25) OVER(),0) AS lexical_score FROM lexical
  ) SELECT COALESCE(d._id,l._id) AS _id,COALESCE(d.document,l.document) AS document,
    COALESCE(d.metadata,l.metadata) AS metadata,
    ${config.denseWeight}*COALESCE(d.dense_score,0)+${1-config.denseWeight}*COALESCE(l.lexical_score,0) AS _score
  FROM normalized_dense d FULL JOIN normalized_lexical l ON d._id=l._id
  ORDER BY _score DESC,_id LIMIT ?`;
}
