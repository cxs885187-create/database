"""Curated translations transcribed from page 1 of the supplied glossary."""

GLOSSARY_TRANSLATIONS = {
    'addition': '加法',
    'alias': '别名 / 共享引用',
    'and': '逻辑与',
    'argument': '实际参数',
    'arithmeticoperator': '算术运算符',
    'assignment': '赋值',
    'associativity': '结合性',
    'backslash': '反斜杠',
    'binary': '二进制',
    'bit': '二进制位',
    'bitwiseAND': '按位与',
    'bitwiseNOT': '按位取反',
    'bitwiseOR': '按位或',
    'bitwiseXOR': '按位异或',
    'bitwiseoperator': '位运算符',
    'Booleanoperator': '布尔运算符',
    'built-infunction': '内置函数',
    'case-sensitive': '区分大小写',
    'chainedcomparison': '链式比较',
    'collection': '集合 / 容器类型',
    'comparisonoperator': '比较运算符',
    'condition': '条件',
    'conditionalstatement': '条件语句',
    'controlflow': '控制流',
    'copy': '复制',
    'debug': '调试',
    'debugging': '调试',
    'decimalplaces': '小数位数',
    'deepcopy': '深复制',
    'defaultparametervalue': '默认参数值',
}


def import_glossary_translations(repository, translations=None):
    translations = translations or GLOSSARY_TRANSLATIONS
    normalized = {word.lower(): translation for word, translation in translations.items()}
    known = repository.lookup(normalized)
    matched = len(known)
    updated = repository.update_translations(normalized)
    return {
        'matched': matched,
        'updated': updated,
        'missing': sorted(set(normalized) - set(known)),
    }
