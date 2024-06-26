import streamlit as st
import pandas as pd
import numpy as np
import re
import os
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix
from sklearn.metrics import classification_report
from collections import defaultdict
import datetime
import time
import math
from nlpaug.augmenter.word import SynonymAug
import json

# NLP
import nltk
nltk.download('punkt')
from nltk.probability import FreqDist
from nltk.tokenize import word_tokenize
import emoji

# Viz
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib as mpl
from wordcloud import WordCloud

#Model IndoBERT
import random
import torch
import torch.nn.functional as F
from torch import optim
from tqdm import tqdm

from transformers import BertForSequenceClassification, BertConfig, BertTokenizer, pipeline, AutoModelForSequenceClassification, AutoTokenizer
from indonlu.utils.data_utils import DocumentSentimentDataset, DocumentSentimentDataLoader
from indonlu.utils.forward_fn import forward_sequence_classification
from indonlu.utils.metrics import document_sentiment_metrics_fn

st.set_page_config(page_title="Sentweet", layout="centered", page_icon="🐦")

def env():
    environment = st.secrets["general"].get("ENVIRONMENT", "localhost")
    if environment == 'production':
        return True
    else:
        return False
    
def crawl_twitter_data(auth_token, search_keyword, limit, filename, start_date=None, end_date=None):
    if not os.path.exists('tweet-harvest'):
        os.system("npm install --global tweet-harvest@2.6.1")
    
    search_phrase = search_keyword.replace(" ", "+")
    date_filter = ""
    if start_date and end_date:
        date_filter = f" since:{start_date} until:{end_date}"
    
    filename = f"{search_keyword}.csv"
    os.system(f"npx --yes tweet-harvest@2.6.1 -o {filename} -s \"{search_phrase}+lang:id{date_filter}\" -l {limit} --token {auth_token}")

@st.cache_resource
def load_model_labeling():
    pretrained = "mdhugol/indonesia-bert-sentiment-classification"
    model = AutoModelForSequenceClassification.from_pretrained(pretrained)
    tokenizer = AutoTokenizer.from_pretrained(pretrained)
    sentiment_analysis = pipeline("sentiment-analysis", model=model, tokenizer=tokenizer)
    label_index = {'LABEL_0': 'positive', 'LABEL_1': 'neutral', 'LABEL_2': 'negative'}
    return sentiment_analysis, label_index

def labeling(df, sentiment_analysis, label_index):
    df['sentiment'] = df['tweet'].apply(lambda x: sentiment_analysis(x)[0]['label'])
    df['sentiment'] = df['sentiment'].map(label_index)
    return df

def donut(sizes, ax, angle=90, labels=None,colors=None, explode=None, shadow=None):
    patches, texts, autotexts = ax.pie(sizes, colors=colors, labels=labels, autopct='%1.1f%%',
                                       startangle=angle, pctdistance=0.8, explode=explode,
                                       wedgeprops=dict(width=0.4), shadow=shadow)
    for i, autotext in enumerate(autotexts):
        autotext.set_text(f"{sizes[i]}\n({autotext.get_text()})")
    plt.axis('equal')
    plt.tight_layout()

def plot_label(df):
    if 'sentiment' in df.columns:
        sizes = df['sentiment'].value_counts()
        labels = ['Sentimen Negatif', 'Sentimen Netral', 'Sentimen Positif']
        colors = ['lightcoral', 'lightskyblue', 'lightgreen']
        explode = (0, 0, 0)

        # Create axes
        f, ax = plt.subplots(figsize=(6, 4))

        # Plot donut
        donut(sizes, ax, 90, labels, colors=colors, explode=explode, shadow=True)
        ax.set_title('Tweet Sentiment Proportions')
        st.pyplot(f)

        st.write("Sebaran Sentimen Dataset:")
        st.write(df['sentiment'].value_counts())
    else:
        st.error("Kolom 'sentiment' tidak ditemukan di dalam CSV.")

def case_folding(df):
    df['tweet'] = df['tweet'].str.lower()
    return df

def data_cleaning(df):
    character = ['.', ',', ';', ':', '-', '...', '?', '!', '(', ')', '[', ']', '{', '}', '<', '>', '"', '/', '\'', '#', '-',
                 '@', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't',
                 'u', 'v', 'w', 'x', 'y', 'z', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O',
                 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']

    # Clean repeated characters
    for i, row in df.iterrows():
        text = row['tweet']
        for char in character:
            charac_long = 5
            while charac_long > 2:
                char_repeat = char * charac_long
                text = text.replace(char_repeat, char)
                charac_long -= 1
        df.at[i, 'tweet'] = text

    # Clean tweets
    for i, row in df.iterrows():
        text = row['tweet']
        # ubah text menjadi huruf kecil
        text = text.lower()
        # ubah enter menjadi spasi
        text = re.sub(r'\n', ' ', text)
        # hapus emoji
        text = emoji.demojize(text)
        text = re.sub(':[A-Za-z_-]+:', ' ', text) # delete emoji
        # hapus emoticon
        text = re.sub(r"([xX;:]'?[dDpPvVoO3)(])", ' ', text)
        # hapus link
        text = re.sub(r"(https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|www\.[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9]+\.[^\s]{2,}|www\.[a-zA-Z0-9]+\.[^\s]{2,})", "", text)
        # hapus usename
        text = re.sub(r"@[^\s]+[\s]?", ' ', text)
        # hapus hashtag
        text = re.sub(r'#(\S+)', r'\1', text)
        # hapus angka dan beberapa simbol
        text = re.sub('[^a-zA-Z,.?!]+',' ',text)
        # hapus karakter berulang
        for char in character:
            charac_long = 5
            while charac_long > 2:
                char_repeat = char * charac_long
                text = text.replace(char_repeat, char)
                charac_long -= 1
        # clear spasi
        text = re.sub('[ ]+',' ',text)
        df.at[i, 'tweet'] = text

    df = df.replace('', np.nan).replace(' ', np.nan).dropna(subset=['tweet'])
    return df

def tokenization(df):
    df['tweet'] = df['tweet'].apply(word_tokenize)
    return df

def normalization(df):
    kamus_alay = pd.read_csv('kamus_alay.csv')
    normalize_word_dict = {row[0]: row[1] for index, row in kamus_alay.iterrows()}

    def normalize_tweet(text):
        return [normalize_word_dict[term] if term in normalize_word_dict else term for term in text]

    df['tweet'] = df['tweet'].apply(normalize_tweet)
    df['tweet'] = df['tweet'].apply(' '.join)
    df = df.replace('', np.nan).replace(' ', np.nan).dropna(subset=['tweet'])
    return df

def augment_and_prepare_data(df_normalized, aug_ratio=0.971813):
    aug = SynonymAug(aug_src='wordnet')
    def augment_text(text, augmenter):
        augmented_text = augmenter.augment(text)
        return augmented_text

    num_ori = df_normalized.shape[0]
    num_aug = int(num_ori * aug_ratio)
    aug_texts = []
    labels = []
    for i in range(num_aug):
        idx = i % num_ori
        text = df_normalized.iloc[idx]['tweet']
        label = df_normalized.iloc[idx]['sentiment']
        aug_texts.append(augment_text(text, aug))
        labels.append(label)
    df_augmented = pd.DataFrame({'tweet': aug_texts, 'sentiment': labels})
    df_normalized_augmented = pd.concat([df_normalized[['tweet', 'sentiment']], df_augmented], ignore_index=True)
    df_normalized_augmented = df_normalized_augmented[['tweet', 'sentiment']]
    df_normalized_augmented.to_csv('data_v2_augmented.csv', header=None, index=False)
    df_normalized_augmented['tweet'] = df_normalized_augmented['tweet'].astype(str)

    return df_normalized_augmented

def get_corpus_and_unique_words(df, column):
    def make_corpus(column):
        corpus_list = []
        for text in column:
            cleaned_list = text.split(' ')
            corpus_list.extend(cleaned_list)

        corpus = ' '.join(corpus_list)
        corpus = re.sub('[ ]+', ' ', corpus)
        return corpus

    corpus = make_corpus(df[column])
    corpus_set = set(corpus.split(' '))
    unique_word_count = len(corpus_set)

    return corpus, unique_word_count

def word_freq(corpus, top=5):
    tokenized_word = word_tokenize(corpus)
    freqdist = FreqDist(tokenized_word)
    freqdist = freqdist.most_common(top)
    label = [tup[0] for tup in freqdist]
    freq = [tup[1] for tup in freqdist]
    df = pd.DataFrame({'word':label, 'freq':freq})
    return df

def plot_word_frequency(corpus_freq):
    plt.style.use('default')
    sns.set(style='ticks', palette='Set2')
    mpl.rcParams['axes.titlesize'] = 20
    mpl.rcParams['axes.titlepad'] = 20
    f, ax1 = plt.subplots(1, figsize=(15, 5))
    sns.barplot(x='word', y='freq', data=corpus_freq, ax=ax1)
    ax1.set_title('Word Frequency in Train Data')
    ax1.tick_params(axis='x', rotation=45)
    st.pyplot(f)

def plot_word_cloud(corpus):
    f, ax2 = plt.subplots(1, figsize=(15, 5))
    ax2.set_title('Word Cloud in Train Data')
    ax2.tick_params(axis='x', rotation=45)
    wordcloud = WordCloud(max_font_size=50, max_words=100, background_color="white").generate(corpus)
    ax2.imshow(wordcloud, interpolation="bilinear")
    st.pyplot(f)

def split_and_save_data(df_normalized_augmented):
    train_set, val_set = train_test_split(df_normalized_augmented, test_size=0.3, stratify=df_normalized_augmented['sentiment'], random_state=1)
    val_set, test_set = train_test_split(val_set, test_size=0.33, stratify=val_set['sentiment'], random_state=1)

    st.write("Train set: " + str(train_set.shape[0]) + " baris (70%)")
    st.write("Validate set: " + str(val_set.shape[0]) + " baris (20%)")
    st.write("Test set: " + str(test_set.shape[0]) + " baris (10%)")

    train_set.to_csv('train_set.tsv', sep='\t', index=False, header=None)
    val_set.to_csv('val_set.tsv', sep='\t', index=False, header=None)
    test_set.to_csv('test_set.tsv', sep='\t', index=False, header=None)

    # Plot donut chart for train set
    train_counts = train_set['sentiment'].value_counts()
    f, ax = plt.subplots(figsize=(6, 4))
    donut(train_counts, ax, labels=train_counts.index, colors=['lightcoral', 'lightskyblue', 'lightgreen'])
    ax.set_title('Train Set Sentiment Proportions')
    st.pyplot(f)

    # Plot donut chart for val set
    val_counts = val_set['sentiment'].value_counts()
    f, ax = plt.subplots(figsize=(6, 4))
    donut(val_counts, ax, labels=val_counts.index, colors=['lightcoral', 'lightskyblue', 'lightgreen'])
    ax.set_title('Validation Set Sentiment Proportions')
    st.pyplot(f)

    # Plot donut chart for test set
    test_counts = test_set['sentiment'].value_counts()
    f, ax = plt.subplots(figsize=(6, 4))
    donut(test_counts, ax, labels=test_counts.index, colors=['lightcoral', 'lightskyblue', 'lightgreen'])
    ax.set_title('Test Set Sentiment Proportions')
    st.pyplot(f)

def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)

def count_param(module, trainable=False):
    if trainable:
        return sum(p.numel() for p in module.parameters() if p.requires_grad)
    else:
        return sum(p.numel() for p in module.parameters())

def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']

def metrics_to_string(metric_dict):
    string_list = []
    for key, value in metric_dict.items():
        string_list.append('{}:{:.2f}'.format(key, value))
    return ' '.join(string_list)

@st.cache_resource
def load_model_bert():
    tokenizer = BertTokenizer.from_pretrained('indobenchmark/indobert-base-p1')
    config = BertConfig.from_pretrained('indobenchmark/indobert-base-p1')
    config.num_labels = DocumentSentimentDataset.NUM_LABELS

    model = BertForSequenceClassification.from_pretrained(
        'indobenchmark/indobert-base-p1',
        config=config,
        ignore_mismatched_sizes=True
    )
    return tokenizer, model

def prepare():
    train_set_path = 'train_set.tsv'
    val_set_path = 'val_set.tsv'
    test_set_path = 'test_set.tsv'
    
    tokenizer, model = load_model_bert()
    train_set = DocumentSentimentDataset(train_set_path, tokenizer, lowercase=True)
    val_set = DocumentSentimentDataset(val_set_path, tokenizer, lowercase=True)
    test_set = DocumentSentimentDataset(test_set_path, tokenizer, lowercase=True)
    
    train_loader = DocumentSentimentDataLoader(dataset=train_set, max_seq_len=512, batch_size=32, num_workers=8, shuffle=True)
    val_loader = DocumentSentimentDataLoader(dataset=val_set, max_seq_len=512, batch_size=32, num_workers=8, shuffle=False)
    test_loader = DocumentSentimentDataLoader(dataset=test_set, max_seq_len=512, batch_size=32, num_workers=8, shuffle=False)
    
    w2i, i2w = DocumentSentimentDataset.LABEL2INDEX, DocumentSentimentDataset.INDEX2LABEL
    return train_loader, val_loader, test_loader, w2i, i2w, tokenizer, model

def test_model_bert_unoptimized(tokenizer, model, texts, i2w):
    results = []
    for text in texts:
        subwords = tokenizer.encode(text)
        subwords = torch.LongTensor(subwords).view(1, -1).to(model.device)

        logits = model(subwords)[0]
        label_idx = torch.topk(logits, k=1, dim=-1)[1].squeeze().item()

        results.append(f"Text: {text} | Label : {i2w[label_idx]} ({F.softmax(logits, dim=-1).squeeze()[label_idx] * 100:.3f}%)")
    return results

def eval_model_bert_unoptimized(model, val_loader, i2w):
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device)
    model.eval()
    torch.set_grad_enabled(False)
    list_hyp_unoptimized, list_label_unoptimized = [], []
    progress_bar = st.progress(0)
    progress_text = st.empty()
    total_batches = len(val_loader)
    
    for i, batch_data in enumerate(val_loader):
        batch_data = tuple(t.to(device) if isinstance(t, torch.Tensor) else t for t in batch_data[:-1])
        _, batch_hyp_unoptimized, batch_label_unoptimized = forward_sequence_classification(model, batch_data, i2w=i2w, device=device)
        list_hyp_unoptimized += batch_hyp_unoptimized
        list_label_unoptimized += batch_label_unoptimized
        progress = (i + 1) / total_batches
        progress_bar.progress(progress)
        progress_text.text(f'Progress: {int(progress * 100)}% ({i + 1}/{total_batches} batches)')
        
    conf_matrix = confusion_matrix(list_label_unoptimized, list_hyp_unoptimized)
    plt.figure(figsize=(10, 8))
    sns.heatmap(conf_matrix, annot=True, fmt='d', cmap='Blues', xticklabels=[i2w[idx] for idx in range(len(i2w))], yticklabels=[i2w[idx] for idx in range(len(i2w))])
    plt.xlabel('Prediction Label')
    plt.ylabel('True Label')
    plt.title('Confusion Matrix Model BERT Unoptimized')
    st.pyplot(plt)
    st.write('Classification Report Model BERT Unoptimized:')
    st.code(classification_report(list_label_unoptimized, list_hyp_unoptimized, target_names=[i2w[idx] for idx in range(len(i2w))]))

    return list_hyp_unoptimized, list_label_unoptimized

def eval_model_bert_finetuned(model, train_loader, val_loader, test_loader, i2w):
    
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device)
    optimizer = optim.AdamW(model.parameters(), lr=5e-5)
    n_epochs = 5
    history = defaultdict(list)
    patience = 2
    best_val_loss = float('inf')
    best_test_loss = float('inf')
    patience_counter = 0
    
    for epoch in range(n_epochs):
        model.train()
        torch.set_grad_enabled(True)
        total_train_loss = 0
        list_hyp_train, list_label = [], []
        train_pbar = tqdm(train_loader, leave=True, total=len(train_loader))
        
        for i, batch_data in enumerate(train_pbar):
            batch_data = tuple(t.to(device) if isinstance(t, torch.Tensor) else t for t in batch_data[:-1])
            loss, batch_hyp, batch_label = forward_sequence_classification(model, batch_data, i2w=i2w, device=device)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            tr_loss = loss.item()
            total_train_loss = total_train_loss + tr_loss
            list_hyp_train += batch_hyp
            list_label += batch_label
            train_pbar.set_description(f"(Epoch {epoch+1}) TRAIN LOSS:{total_train_loss/(i+1):.4f} LR:{get_lr(optimizer):.8f}")
        
        metrics = document_sentiment_metrics_fn(list_hyp_train, list_label)
        st.write(f"(Epoch {epoch+1}) TRAIN LOSS:{total_train_loss/(i+1):.4f} {metrics_to_string(metrics)} LR:{get_lr(optimizer):.8f}")
        history['train_acc'].append(metrics['ACC'])
        model.eval()
        torch.set_grad_enabled(False)
        total_loss = 0
        list_hyp, list_label = [], []
        pbar = tqdm(val_loader, leave=False, total=len(val_loader))
        
        for i, batch_data in enumerate(pbar):
            batch_data = tuple(t.to(device) if isinstance(t, torch.Tensor) else t for t in batch_data[:-1])
            loss, batch_hyp, batch_label = forward_sequence_classification(model, batch_data, i2w=i2w, device=device)
            valid_loss = loss.item()
            total_loss = total_loss + valid_loss
            list_hyp += batch_hyp
            list_label += batch_label
            metrics = document_sentiment_metrics_fn(list_hyp, list_label)
            pbar.set_description(f"VALID LOSS:{total_loss/(i+1):.4f} {metrics_to_string(metrics)}")

        metrics = document_sentiment_metrics_fn(list_hyp, list_label)
        st.write(f"(Epoch {epoch+1}) VALID LOSS:{total_loss/(i+1):.4f} {metrics_to_string(metrics)}")
        history['val_acc'].append(metrics['ACC'])
        
        if total_loss < best_val_loss:
            best_val_loss = total_loss
            patience_counter = 0
            torch.save(model.state_dict(), 'best_model_bert_finetuned_val.pt')
        else:
            patience_counter += 1
        
        if patience_counter >= patience:
            st.write(f'Early stopping on epoch {epoch+1}')
            break
        
        val_df = pd.read_csv('val_set.tsv', sep='\t', names=['tweet', 'sentiment'])
        val_df['pred'] = list_hyp
        val_df.head()
        val_df.to_csv('val_set_pred.csv', index=False)
        
        model.load_state_dict(torch.load('best_model_bert_finetuned_val.pt'))
        model.eval()
        torch.set_grad_enabled(False)
        total_loss, total_correct, total_labels = 0, 0, 0
        list_hyp, list_label = [], []
        pbar = tqdm(test_loader, leave=False, total=len(test_loader))
        
        for i, batch_data in enumerate(pbar):
            batch_data = tuple(t.to(device) if isinstance(t, torch.Tensor) else t for t in batch_data[:-1])
            loss, batch_hyp, batch_label = forward_sequence_classification(model, batch_data, i2w=i2w, device=device)
            valid_loss = loss.item()
            total_loss = total_loss + valid_loss
            list_hyp += batch_hyp
            list_label += batch_label
            metrics = document_sentiment_metrics_fn(list_hyp, list_label)
            pbar.set_description(f"TEST LOSS:{total_loss/(i+1):.4f} {metrics_to_string(metrics)}")
                   
        metrics = document_sentiment_metrics_fn(list_hyp, list_label)
        st.write(f"(Epoch {epoch+1}) TEST LOSS:{total_loss/(i+1):.4f} {metrics_to_string(metrics)}")
        history['test_acc'].append(metrics['ACC'])
        
        if total_loss < best_test_loss:
            best_test_loss = total_loss
            patience_counter = 0
            torch.save(model.state_dict(), 'best_model_bert_finetuned_test.pt')
        else:
            patience_counter += 1

        if patience_counter >= patience:
            st.write(f'Early stopping on epoch {epoch+1}')
            break
        
        test_df = pd.read_csv('test_set.tsv', sep='\t', names=['tweet', 'sentiment'])
        test_df['pred'] = list_hyp
        test_df.head()
        test_df.to_csv('test_set_pred.csv', index=False)

    return history, val_df, test_df

def eval_model_bert_finetuned_prod():
    with open('finetuned.json', 'r') as f:
        data = json.load(f)

    pbar = st.progress(0)
    for i, item in enumerate(data):
        time.sleep(3)
        percentage = i / (len(data) - 1)
        pbar.progress(percentage)
        st.write(f"Epoch {item['epoch']} {item['set_data']} LOSS:{item['loss']:.4f} ACC:{item['acc']:.2f} F1:{item['f1']:.2f} REC:{item['rec']:.2f} PRE:{item['pre']:.2f} BATCH:{item['batch']} TIME:{item['time']:.2f}s")

def learning_curve(history):
    plt.figure(figsize=(8, 6))
    plt.plot(history['train_acc'], label='train acc')
    plt.plot(history['val_acc'], label='val acc')
    plt.title('Learning Curve')
    plt.xlabel('Epoch')
    plt.ylabel('Accuracy')
    plt.legend()
    st.pyplot(plt)

def learning_curve_prod():
    with open('finetuned.json', 'r') as f:
        data = json.load(f)
    history = {'train_acc': [], 'val_acc': []}
    for item in data:
        if item['set_data'] == 'TRAIN':
            history['train_acc'].append(item['acc'])
        else:
            history['val_acc'].append(item['acc'])
    learning_curve(history)

def test_model_bert_finetuned(tokenizer, model, texts, i2w):
    results = []
    for text in texts:
        subwords = tokenizer.encode(text)
        subwords = torch.LongTensor(subwords).view(1, -1).to(model.device)

        logits = model(subwords)[0]
        label_idx = torch.topk(logits, k=1, dim=-1)[1].squeeze().item()

        results.append(f"Text: {text} | Label : {i2w[label_idx]} ({F.softmax(logits, dim=-1).squeeze()[label_idx] * 100:.3f}%)")
    return results

def test_model_bert_finetuned_prod(texts):
    with open('test.json', 'r') as f:
        data = json.load(f)
    results = []
    for text in texts:
        for item in data:
            results.append(f"Text: {text} | Label : {item['label']} ({item['score'] * 100:.3f}%)")
    return results

def conf_class_finetuned_val(val_df):
    val_real = val_df.sentiment
    val_pred = val_df.pred
    
    def show_conf_matrix(confusion_matrix):
        plt.figure(figsize=(10, 8))
        hmap = sns.heatmap(confusion_matrix, annot=True, fmt="d", cmap="Blues")
        hmap.yaxis.set_ticklabels(hmap.yaxis.get_ticklabels(), rotation=0, ha='right')
        hmap.xaxis.set_ticklabels(hmap.xaxis.get_ticklabels(), rotation=30, ha='right')
        plt.ylabel('True sentiment')
        plt.xlabel('Predicted sentiment');
        st.pyplot(plt)
        plt.close()

    cm = confusion_matrix(val_real, val_pred)
    df_cm = pd.DataFrame(cm, index=['positive', 'neutral', 'negative'], columns=['positive', 'neutral', 'negative'])
    show_conf_matrix(df_cm)
    st.code(classification_report(val_real, val_pred, target_names=['positive', 'neutral', 'negative']))
    
def conf_class_finetuned_test(test_df):
    test_real = test_df.sentiment
    test_pred = test_df.pred
    
    def show_conf_matrix(confusion_matrix):
        plt.figure(figsize=(10, 8))
        hmap = sns.heatmap(confusion_matrix, annot=True, fmt="d", cmap="Blues")
        hmap.yaxis.set_ticklabels(hmap.yaxis.get_ticklabels(), rotation=0, ha='right')
        hmap.xaxis.set_ticklabels(hmap.xaxis.get_ticklabels(), rotation=30, ha='right')
        plt.ylabel('True sentiment')
        plt.xlabel('Predicted sentiment');
        st.pyplot(plt)
        plt.close()
    
    cm = confusion_matrix(test_real, test_pred)
    df_cm = pd.DataFrame(cm, index=['positive', 'neutral', 'negative'], columns=['positive', 'neutral', 'negative'])
    show_conf_matrix(df_cm)
    st.code(classification_report(test_real, test_pred, target_names=['positive', 'neutral', 'negative']))

def conf_class_finetuned_prod():
    def show_conf_matrix(confusion_matrix):
        plt.figure(figsize=(10, 8))
        hmap = sns.heatmap(confusion_matrix, annot=True, fmt="d", cmap="Blues")
        hmap.yaxis.set_ticklabels(hmap.yaxis.get_ticklabels(), rotation=0, ha='right')
        hmap.xaxis.set_ticklabels(hmap.xaxis.get_ticklabels(), rotation=30, ha='right')
        plt.ylabel('True sentiment')
        plt.xlabel('Predicted sentiment');
        st.pyplot(plt)
        plt.close()
        
    val_real = pd.read_csv('archive/val_set_pred.csv').sentiment
    val_pred = pd.read_csv('archive/val_set_pred.csv').pred
    cm = confusion_matrix(val_real, val_pred)
    df_cm = pd.DataFrame(cm, index=['positive', 'neutral', 'negative'], columns=['positive', 'neutral', 'negative'])
    show_conf_matrix(df_cm)
    st.code(classification_report(val_real, val_pred, target_names=['positive', 'neutral', 'negative']))
    
    test_real = pd.read_csv('archive/test_set_pred.csv').sentiment
    test_pred = pd.read_csv('archive/test_set_pred.csv').pred
    cm = confusion_matrix(test_real, test_pred)
    df_cm = pd.DataFrame(cm, index=['positive', 'neutral', 'negative'], columns=['positive', 'neutral', 'negative'])
    show_conf_matrix(df_cm)
    st.code(classification_report(test_real, test_pred, target_names=['positive', 'neutral', 'negative']))

def main():
    if env() is True:
        st.toast("Running in production environment", icon="🚀")
    else:
        st.toast("Running in development environment", icon="🚀")
        
    st.html("<div style='display: flex; align-items: center'><img src='https://cdn-icons-png.flaticon.com/512/2525/2525779.png' width='64'><h1>Sentweet</h1></div>")
    st.caption("Created by: [Kelompok 10](https://x.com/sendomoka) Inspired by: [Helmi Satria](https://x.com/helmisatria_)")
    st.html("Aplikasi untuk crawl tweet <code>berbahasa Indonesia</code> berdasarkan keyword dan akan dianalisis sentimennya, pre-trained model BERT dan Naive Bayes.")
    tabs = st.tabs(["Crawling + Sentiment Analysis", "Upload CSV + Sentiment Analysis"])

    with tabs[0]:
        # Tab untuk crawling dan analisis sentimen
        st.info("Pastikan Anda sudah login ke Twitter dan mendapatkan auth token, jika belum, silahkan login terlebih dahulu ke Twitter kemudian inspect element > application > cookies > auth_token > value")
        auth_token = st.text_input("Twitter Auth Token", value="8e0c51ebff4c16ef59890bcf1cc04af4e7e73cbd", help="Masukkan Twitter Auth Token", type="password")
        search_keyword = st.text_input("Search Keyword", value="biznet", help="Masukkan keyword untuk search di Twitter")
        limit = st.number_input("Limit", min_value=1, value=50, help="Masukkan jumlah tweets yang akan di-crawl, max 5k tweets per request")
        today = datetime.date.today()
        date_range = st.date_input("Date Range", value=[datetime.date(2019, 1, 1), datetime.date(2024, 6, 15)], help="Pilih range tanggal untuk search tweet", min_value=datetime.date(2006, 3, 21), max_value=today, key="date_range")
        
        start_date, end_date = (date_range if date_range else (None, None))
        
        if st.button("Goooo‼️‼️🗣️🗣️🔥🔥💥💥"):
            with st.spinner("Mulung tweet..."):
                start_time = time.time()
                tweets_per_second = 20 / 10
                estimated_time = (limit / tweets_per_second) / 60
                remaining_time = math.ceil(estimated_time)
                st.info(f"Perkiraan selesai: {remaining_time} menit")
                crawl_twitter_data(auth_token, search_keyword, limit, None, start_date, end_date)
                end_time = time.time()
                duration = end_time - start_time
                st.success(f"Crawling data selesai: {duration:.2f} detik.")
            
            filename = os.path.join(os.getcwd(), 'tweets-data', f"{search_keyword}.csv")
            if os.path.exists(filename):
                df = pd.read_csv(filename)
                if 'full_text' in df.columns:
                    df_tweet = df[['full_text']].rename(columns={'full_text': 'tweet'})
                    st.session_state.data = df_tweet
                    st.write("### Crawled Data")
                    st.write(df)
                    st.write(df_tweet)
                    st.write(f"Number of rows: {len(df)}")
                else:
                    st.error("Kolom 'full_text' tidak ditemukan di dalam CSV.")
            else:
                st.error("File CSV tidak ditemukan.")
                
        st.write("#### Label Sentiment")
        if st.button("Sentimenin...") and st.session_state.data is not None:
            st.warning("Labeling sentimen ini menggunakan model dari luar sehingga ada kemungkinan kurang akurat dan disarankan melakukan labeling sentimen secara manual.")
            sentiment_analysis, label_index = load_model_labeling()
            with st.spinner("Labeling sentimen..."):
                st.session_state.data = labeling(st.session_state.data, sentiment_analysis, label_index)
                st.success("Labeling selesai!")
                st.write("### Labeled Data")
                st.write(st.session_state.data)
                filename = os.path.join(os.getcwd(), 'tweets-data', f"{search_keyword}-sentimented.csv")
                st.session_state.data.to_csv(filename, index=False)
        else:
            st.warning("Crawl data terlebih dahulu sebelum melakukan labeling sentimen.")
        
        st.write("#### Contoh Data")
        folder_path = os.path.join(os.getcwd(), 'tweets-data')
        all_files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f)) and f.endswith('.csv')]
        for file in all_files:
            file_path = os.path.join(folder_path, file)
            df = pd.read_csv(file_path)
            st.write(f"Data dari file: {file}")
            st.dataframe(df)
            
    with tabs[1]:
        # Upload file CSV
        uploaded_file = st.file_uploader("Unggah file CSV", type="csv")
        text1 = st.text_input("Masukkan teks positif untuk diprediksi", value="wifi biznet cepat dan lancar", key="text1")
        text2 = st.text_input("Masukkan teks netral untuk diprediksi", value="wifi biznet stabil atau tidak?", key="text2")
        text3 = st.text_input("Masukkan teks negatif untuk diprediksi", value="wifi biznet lambat sekali", key="text3")
        
        if st.button("Go") and uploaded_file:
            # Read dataset
            df = pd.read_csv(uploaded_file)
            st.write("Dataset Awal (" + str(df.shape[0]) + " baris):", df)
            plot_label(df)
                
            # Case folding
            df_case_folding = case_folding(df.copy())
            st.write("Case Folding:")
            st.write(df_case_folding)

            # Data cleaning
            df_cleaned = data_cleaning(df_case_folding.copy())
            st.write("Data Cleaning:")
            st.write(df_cleaned)

            # Tokenization
            df_tokenized = tokenization(df_cleaned.copy())
            st.write("Tokenization:")
            st.write(df_tokenized)

            # Normalization
            df_normalized = normalization(df_tokenized.copy())
            st.write("Normalization (" + str(df_normalized.shape[0]) + " baris):")
            st.write(df_normalized)

            # Augmentation
            df_normalized_augmented = augment_and_prepare_data(df_normalized.copy(), aug_ratio=0.971813)
            st.write("Augmentation (" + str(df_normalized_augmented.shape[0]) + " baris):")
            st.write(df_normalized_augmented)
            
            # Tokenize corpus
            corpus, unique_word_count = get_corpus_and_unique_words(df_normalized_augmented, 'tweet')
            st.write("Total unique words: " + str(unique_word_count))

            # Word Frequency
            corpus_freq = word_freq(corpus, top=20)
            plot_word_frequency(corpus_freq)
            
            # Cloud for corpus
            corpus, unique_word_count = get_corpus_and_unique_words(df_normalized_augmented, 'tweet')
            plot_word_cloud(corpus)
            
            # Split data
            split_and_save_data(df_normalized_augmented)
              
            # Load model
            set_seed(27)
            train_loader, val_loader, test_loader, w2i, i2w, tokenizer, model = prepare()
            st.write("Word to index:")
            st.json(w2i)
            st.write("Index to word:")
            st.json(i2w)
            
            # Test model BERT Unoptimized
            st.write("Test model BERT Unoptimized:")
            tokenizer, model = load_model_bert()
            texts = [text1, text2, text3]
            results_unoptimized = test_model_bert_unoptimized(tokenizer, model, texts, i2w)
            for result_unoptimized in results_unoptimized:
                st.write(result_unoptimized)
            
            # Eval model BERT Unoptimized
            st.write("Eval model BERT Unoptimized:")
            eval_model_bert_unoptimized(model, val_loader, i2w)
            
            # Eval model BERT Finetuned
            st.write("Eval model BERT Finetuned:")
            if env() is True:
                eval_model_bert_finetuned_prod()
            else:
                history, val_df, test_df = eval_model_bert_finetuned(model, train_loader, val_loader, test_loader, i2w)
            
            # Learning curve
            st.write("Learning curve:")
            if env() is True:
                learning_curve_prod()
            else:
                learning_curve(history)
            
            # Read Prediction
            if env() is False:
                df_val_pred = pd.read_csv('val_set_pred.csv')
                st.write("Validation Prediction:")
                st.write(df_val_pred)
                df_test_pred = pd.read_csv('test_set_pred.csv')
                st.write("Test Prediction:")
                st.write(df_test_pred)
                        
            # Test model BERT Finetuned
            st.write("Test model BERT Finetuned:")
            texts = [text1, text2, text3]
            if env() is True:
                test_model_bert_finetuned_prod(texts)
            else:
                results_finetuned = test_model_bert_finetuned(tokenizer, model, texts, i2w)
                for result_finetuned in results_finetuned:
                    st.write(result_finetuned)
            
            # Show Confusion Matrix and Classification Report Model BERT Finetuned
            if env() is True:
                conf_class_finetuned_prod()
            else:
                st.write("Validation Confusion Matrix and Classification Report:")
                conf_class_finetuned_val(df_val_pred)
                st.write("Test Confusion Matrix and Classification Report:")
                conf_class_finetuned_test(df_test_pred)
        else:
            st.write("Silakan unggah file CSV terlebih dahulu.")
            
if __name__ == '__main__':
    main()
