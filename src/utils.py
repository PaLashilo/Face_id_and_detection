import os
import yaml
import subprocess
import zipfile
import shutil
import csv
from pathlib import Path

import cv2
import torch
from numpy import inf
import torch.nn as nn
import torchvision
import torchvision.transforms as tf
from torchvision import transforms
import torch.nn.functional as F
from PIL import Image, ImageDraw
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import pandas as pd
import timm

import src.models as models


# функция для загрузки конфига
def get_options():
    """
    Загрузка конфигурационных опций из файла config.yaml.

    Returns:
    dict: Словарь с конфигурационными опциями.

    """
    options_path = 'config.yaml'
    with open(options_path, 'r') as option_file:
        options = yaml.safe_load(option_file)
    return options

config = get_options()


transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Lambda(lambda x: x / 255.0), # normalization
])



### ФУНКЦИИ ДЛЯ СКАЧИВАНИЯ И ОБРАБОТКИ ДАТАСЕТОВ ###

# функция загрузки файла kaggle.json
def get_kaggle_json_file():

    """
    Загрузка файла kaggle.json через Google Colab.

    Returns:
    None

    """

    from google.colab import files
    print('ЗАГРУЗИТЕ kaggle.json ФАЙЛ')

    uploaded = files.upload()

    for fn in uploaded.keys():
        print('User uploaded file "{name}" with length {length} bytes'.format(
            name=fn, length=len(uploaded[fn])))


# функция исполнения команд в консоли
def execute_terminal_comands(commands):

    """
    Выполнение команд в терминале и возврат результатов.

    Parameters:
    - commands (list): Список команд для выполнения в терминале.

    Returns:
    list: Список результатов выполнения каждой команды в терминале.

    """

    r = []
    for command in commands:
        r.append(subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    return r


#Функция загрузки отдельного датасета
def download_dataset_from_kaggle(full_name_of_dataset, name_of_dataset ):

    """
    Скачивание датасета с кагла, перемещение в папку и разархивирование

    Parameters:
    - full_name_of_dataset (str): Полное имя датасета на Kaggle, включая пользователя и название датасета.
    - name_of_dataset (str): Название датасета, используемое для создания папки и сохранения архива.

    Returns:
    None

    """

    print(f'\nНачинаю скачачивать датасет: {name_of_dataset}')

    download_face_detection_dataset = [
        f"kaggle datasets download -d {full_name_of_dataset}",
        "mkdir data",
        f"mv {name_of_dataset}.zip data/"
        ]
    
    execute_terminal_comands(download_face_detection_dataset)
 
    # разархивирование датасета
    data_path = Path("data/")
    image_path = data_path / name_of_dataset
    with zipfile.ZipFile(data_path / f"{name_of_dataset}.zip", "r") as zip_ref:
        print(f"Unzipping dataset {name_of_dataset}")
        zip_ref.extractall(image_path)


def download_datasets_from_kaggle():

    """
    скачивание всех датасетов 
    """

    get_kaggle_json_file()

    # перемещение файла kaggle json в место, где его ожидает библиотека kaggle чтоб скачать датасет
    move_kaggle_json_file = [
        "mkdir -p ~/.kaggle/",
        "mv kaggle.json ~/.kaggle/",
        "chmod 600 ~/.kaggle/kaggle.json"
    ]
    execute_terminal_comands(move_kaggle_json_file)

    # Скачать датасет с лицами 10к
    download_dataset_from_kaggle('fareselmenshawii/face-detection-dataset', 'face-detection-dataset')

    # Скачать датасет с комнатами
    download_dataset_from_kaggle('robinreni/house-rooms-image-dataset', 'house-rooms-image-dataset')

    # Скачать датасет с лицами 3к
    download_dataset_from_kaggle('sbaghbidi/human-faces-object-detection', 'human-faces-object-detection')

    # Скачать датасет с триплетами селебА
    download_dataset_from_kaggle('quadeer15sh/celeba-face-recognition-triplets', 'celeba-face-recognition-triplets')
    

# препроцессинг датасета с 10к картинками для более удобной работы с ним
def preprocessing_of_face_detection_dataset():

    """
    Предобработка датасета face_detection_dataset
    """

    print('Начинаю обработку датасета face_detection_dataset')
    
    if config['use_colab']:
        root = '/content/Face_id_and_detection/'
    else:
        root = ''

    def move_all_files(name):
        # Пути к папкам train и val
        train_path = f"{root}data/face-detection-dataset/{name}/train"
        val_path = f"{root}data/face-detection-dataset/{name}/val"

        # Функция для перемещения файлов из source_dir в target_dir
        def move_files(source_dir, target_dir):
            # Получаем список файлов в исходной директории
            files = os.listdir(source_dir)

            # Перемещаем каждый файл в целевую директорию
            for file_name in files:
                source_file = os.path.join(source_dir, file_name)
                target_file = os.path.join(target_dir, file_name)
                shutil.move(source_file, target_file)

        # Перемещаем файлы из папки train в /content/data/face-detection-dataset/labels/
        move_files(train_path, f"{root}data/face-detection-dataset/{name}/")

        # Перемещаем файлы из папки val в /content/data/face-detection-dataset/labels/
        move_files(val_path, f"{root}data/face-detection-dataset/{name}/")

        # Удаляем пустые папки train и val
        os.rmdir(train_path)
        os.rmdir(val_path)

    for name in ['labels', 'images']:
        move_all_files(name)
        

    # Папки с файлами .txt и папка с изображениями
    labels2_dir = f"{root}data/face-detection-dataset/labels2"


    # Путь к итоговому CSV файлу
    csv_file_path = f"{root}data/face-detection-dataset/labels_and_coordinates.csv"

    # Открываем CSV файл для записи
    with open(csv_file_path, mode='w', newline='') as csv_file:
        fieldnames = ['name', 'x1', 'y1', 'x2', 'y2']
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

        # Записываем заголовки CSV файла
        writer.writeheader()

        # Проходим по каждому файлу .txt в папке labels2
        for filename in os.listdir(labels2_dir):
            if filename.endswith(".txt"):
                file_path = os.path.join(labels2_dir, filename)

                # Открываем файл .txt для чтения
                with open(file_path, 'r') as txt_file:
                    lines = txt_file.readlines()

                    # Проверяем количество строк в файле
                    if len(lines) <= 1:
                        # Получаем имя файла без расширения
                        name = filename[:-4]

                        # Получаем x1, y1, x2, y2 из первой строки
                        parts = lines[0].split()
                        if len(parts) == 6 and parts[0] == "Human" and parts[1] == "face":
                            x1, y1, x2, y2 = map(float, parts[2:])

                            # Записываем данные в CSV файл
                            writer.writerow({'name': name, 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2})

    print(f"Данные записаны в {csv_file_path}")


# функция для проверки и дозагрузки датасетов на локальную машину
def check_if_datasets_are_downloaded():

    """
    Проверка, скачаны ли датасеты локально и если нет, то их скачивание. 
    """

    if not os.path.exists('/.kaggle/kaggle.json'):
        print('Moving kaggle file')
        #check if we have kaggle.json file
        move_kaggle_json_file = [
            "mkdir -p ~/.kaggle/",
            "mv kaggle.json ~/.kaggle/",
            "chmod 600 ~/.kaggle/kaggle.json"
        ]
        execute_terminal_comands(move_kaggle_json_file)


    #check if three thausand dataset exists
    if not os.path.exists('data/human-faces-object-detection'):
        print('\nDOWNLOADING three thausand dataset')
        download_dataset_from_kaggle('sbaghbidi/human-faces-object-detection', 'human-faces-object-detection')

    #check if three thausand dataset exists
    if not os.path.exists('data/house-rooms-image-dataset'):
        print('\nDOWNLOADING house-rooms-image-dataset')
        download_dataset_from_kaggle('robinreni/house-rooms-image-dataset', 'house-rooms-image-dataset')

    #check if three thausand dataset exists
    if not os.path.exists('data/face-detection-dataset'):
        print('\nDOWNLOADING face-detection-dataset (10)')
        download_dataset_from_kaggle('fareselmenshawii/face-detection-dataset', 'face-detection-dataset')
        preprocessing_of_face_detection_dataset()

    #check if celebA triplets dataset exists
    if not os.path.exists('data/celeba-face-recognition-triplets'):
        print('\nDOWNLOADING celeba-face-recognition-triplets')
        download_dataset_from_kaggle('/quadeer15sh/celeba-face-recognition-triplets', 'celeba-face-recognition-triplets')

    print('\nall datasets are in place')


# полный цикл загрузки и обработки датасетов для колаба
def colab():
    """
    Функция, которая собирает все функции скачивания и подготовки датасетов в гугл колаб
    """
    
    download_datasets_from_kaggle()

    preprocessing_of_face_detection_dataset()

    print('\nall a datasets are in place')
    print('\n DONE WITH COLAB')



### ФУНКЦИИ ДЛЯ РАБОТЫ ###


def save_img(img, pred, epoch):

    """
    Сохранение изображения с нарисованным предсказанным bounding box.

    Parameters:
    - img: Изображение в формате numpy array или torch.Tensor.
    - pred: Тензор предсказанных bounding box в формате [x1, y1, x2, y2].
    - epoch: Номер эпохи, используемый для формирования имени сохраняемого файла.

    Returns:
    None

    """

    img = img.numpy() if isinstance(img, torch.Tensor) else img
    
    cur_height, cur_width = img.shape[:2]
    
    # Convert prediction tensor to a list of bounding box coordinates
    bbox = pred.tolist()
    x1, y1, x2, y2 = bbox
    x1 = x1/128*cur_width
    x2 = x2/128*cur_width
    y1 = y1/128*cur_height
    y2 = y2/128*cur_height
    bbox = [x1, y1, x2, y2]
    
    # Create a PIL Image from the numpy array
    img = Image.fromarray(np.uint8(img))
    
    # Draw bounding boxes on the image
    draw = ImageDraw.Draw(img)
    draw.rectangle(bbox, outline="red")
    save_path = f"./results/{epoch}_epoch.jpg"
    # Create the directory if it doesn't exist
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    # Save the image to the specified path
    img.save(save_path)
    
    # print(f"Saved image with bounding box to {save_path}")
    

def save_img_after_epoch(path_to_img, mdl, epoch, device):

    """
    Загружает изображение, обрабатывает его моделью после указанной эпохи обучения и сохраняет результат.

    Parameters:
    - path_to_img (str): Путь к изображению.
    - mdl (torch.nn.Module): Обученная модель PyTorch.
    - epoch (int): Номер эпохи обучения.
    - device (torch.device): Устройство, на котором выполнять вычисления (например, 'cuda' для GPU или 'cpu' для CPU).
    """

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Lambda(lambda x: x / 255.0), # normalization
    ])
    with torch.no_grad():
        img = cv2.imread(path_to_img)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_to_input = cv2.resize(img, (config['img_size'], config['img_size']))

        img_to_input = transform(img_to_input)
        img_to_input = img_to_input.to(device)

        pred = mdl(img_to_input.unsqueeze(0))
        
      
        save_img(img, pred[0][1:], epoch)



# функция изменения размеров bbox под размер изображения с камеры 
def rescale_coordinates(bbox, size):
    # Извлекаем координаты из тензора
    height, width = size[:2]
    # height, width = height *1.25, width *1.7
    x1, y1, x2, y2 = bbox
    
    # Масштабирование координат
    x1 = int((x1 / config['img_size']) * width)
    y1 = int((y1 / config['img_size']) * height)
    x2 = int((x2 / config['img_size']) * width)
    y2 = int((y2 / config['img_size']) * height)
    

    return [x1, y1, x2, y2]


def cam_capture(source=0, model=None, bbox_func=None, limit=inf):

    """""


    source - источник видео, если 0,то это камера ноутбука
    model - модель, выдающая координаты
    bbox_func - функция, котороая строит изображение с bounding box'ом на основе предиктов модели
    limit - количество милисекунд, в течение которых работает камера

    """""

    cap = cv2.VideoCapture(source)
    i = 0 

    while i<=limit:

        ret, frame = cap.read()

        if not ret:
            print("Failed to grab frame")
            break

        
        # Преобразуем изображение из BGR в RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Изменяем размер изображения до 126x126
        resized_frame = cv2.resize(rgb_frame, (128, 128))
        
        pic_tens = transform(resized_frame)

    
        with torch.no_grad():

            res = model(pic_tens.unsqueeze(0))
        
        
        bbox = res[0][1:].tolist()
        print(bbox)
        # bbox = res[0].tolist()[1:]

        coord = rescale_coordinates(bbox, frame.shape)
        print(coord)
        cv2.rectangle(frame, (coord[0], coord[1]), ( coord[2], coord[3]), (0, 0, 255), 2)
        
  
        cv2.imshow("Camera Feed with BBox", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        i += 1
       

    cap.release()
    cv2.destroyAllWindows()


def crop(pic, coords, scale=2, size=256):
    
    '''
    Обрезает изображение вокруг заданных координат и берет площадь не только по рамкам, а вокруг или внутри. 

    Параметры:
    pic (tensor): Входное изображение.
    coords (list): Список координат [x_min, y_min, x_max, y_max] рамки.
    scale (float): Фактор скалирования рамки (во сколько раз обрезанное изображение больше рамки). По умолчанию 2.
    size (int): Размер выходного изображения. По умолчанию 256.

    Возвращает:
    tensor: Обрезанное и измененное по размеру изображение.
    '''
    
    pic_width = pic.shape[2]
    pic_height = pic.shape[1]
        
    
    center = (0.5*(coords[2]+coords[0]), 
              0.5*(coords[3]+coords[1]))
    
    width = scale*(coords[2]-coords[0])
    height = scale*(coords[3]-coords[1])
    
    side = min(max(width, height), min(pic_width, pic_height))
    
    bot_right = [min(center[0]+side/2, pic_width), 
                 min(center[1]+side/2, pic_height)]
    
    x0 = max(0, bot_right[0] - side)
    y0 = max(0, bot_right[1] - side)
    
    res = tf.functional.resized_crop(pic, 
                                     int(y0), 
                                     int(x0), 
                                     int(min(side, pic_height)), 
                                     int(min(side, pic_width)), 
                                     size=size,
                                     antialias=True)
    
    return res


def recognition_cam(source=0, 
                model=None,
                embedding_model=None, 
                database_path = None,
                limit=inf):

    """""
    source - источник видео, если 0,то это камера ноутбука
    model - модель, выдающая координаты
    embedding_model - модель для эмбеддингов
    database_path = путь к базе данных в формате csv
    limit - количество милисекунд, в течение которых работает камера

    """""

    cap = cv2.VideoCapture(source)
    database = pd.read_csv(database_path, index_col=0)
    i = 0 

    prev = 0

    while i<=limit:

        ret, frame = cap.read()

        if not ret:
            print("Failed to grab frame")
            break

        
        # Преобразуем изображение из BGR в RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Изменяем размер изображения до 128x128
        resized_frame = cv2.resize(rgb_frame, (128, 128))
        


        # pic_tens = tf.ToTensor()(resized_frame)
        pic_tens = transform(resized_frame)

        with torch.no_grad():
            res = model(pic_tens.unsqueeze(0))
        
        # print('res - ', res)
        if res[0][0] > 0.9:
            

            bbox = res[0][1:] #*0.5+prev*0.5
        
            coord = rescale_coordinates(bbox, frame.shape)
        

        
        
            cropped = crop(tf.ToTensor()(rgb_frame), coord, size=160, scale=1.5).unsqueeze(0)
        
        
            base = torch.from_numpy(database.values)
        


            embedding = embedding_model(cropped)
       
            distances = (base-embedding).pow(2).sum(axis=1)

            
            if torch.min(distances) > 1.2:
                name = 'unknown'
            else: 
                person_id = torch.argmin(distances).item()
                name = database.index[person_id]
       
      
            cv2.rectangle(frame, (coord[0], coord[1]), (coord[2], coord[3]), (0, 0, 255), 2)
            cv2.putText(frame , f'{name}', (coord[0], coord[1]), cv2.FONT_HERSHEY_SIMPLEX, fontScale=1, thickness = 2, color = (0, 0, 255))

        

        cv2.imshow("Camera Feed with BBox", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        i += 1
    
    cap.release()
    cv2.destroyAllWindows()


def add2db(folder_path, owner, rec_model):

    """
    Add images from the specified folder to a database.

    Parameters:
    - folder_path (str): Path to the folder containing the photos.
    - owner (str): Name of the person in the photos.
    - model: The model providing coordinates.
    - rec_model: The model for embeddings.

    Returns:
    - cropped_imgs (list): List of PIL images after cropping.
    """
    
    pic_list = os.listdir(folder_path)
    if os.path.exists("Database.csv"):
        database = pd.read_csv("Database.csv")
    else:
        database = pd.DataFrame(columns=["name"] + [f"emb{i}" for i in range(512)])

    cropped_imgs = []
    count_image = 0
    database_have_such_name = owner in database.name.values

    for pic in pic_list:
        if pic != ".DS_Store":
            if not database_have_such_name:
                image = cv2.imread(f'{folder_path}/{pic}')
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

                image_for_detection = cv2.resize(image, (128, 128))
                image_for_detection = transform(image_for_detection)

                image_for_recognition = cv2.resize(image, (160, 160))
                image_to_crop = tf.ToTensor()(image_for_recognition)
                
                with torch.no_grad():
                    
                    cropped_image = image_to_crop
                    if count_image==0:
                        embedding = rec_model(cropped_image.unsqueeze(0)).detach().numpy()
                    else:
                        embedding += rec_model(cropped_image.unsqueeze(0)).detach().numpy()

                cropped_imgs.append(tf.ToPILImage()(cropped_image))
                count_image += 1
            else:
                print("Name exists, enter new name or delete old")
                break

    if  not database_have_such_name:

        embedding = embedding/count_image

        database.loc[database.shape[0]] = [owner] + np.array(embedding/count_image)[0].tolist()
        database.to_csv(f'Database.csv', index=False)

    return cropped_imgs



def drop_from_database(value_to_drop):
    """
    Удаляет строки из базы данных, сохраненной в файле 'Database.csv', где значение в столбце 'name' равно указанному значению.

    Параметры:
    - value_to_drop (str): Значение в столбце 'name', строки с которым следует удалить из базы данных.

    Пример использования:
    drop_from_database('John Doe')

    Примечание:
    Если файл 'Database.csv' не существует, будет выведено сообщение "Database doesn't exists".
    """
    import os
    import pandas as pd

    if os.path.exists("Database.csv"):
        database = pd.read_csv("Database.csv")
        database = database.loc[database['name'] != value_to_drop]
        database.to_csv(f'Database.csv', index=False)
    else:
        print("Database doesn't exist")



def plot_images_with_bboxes(batch):
    """
    :param images: Tensor of shape (batch_size, channels, height, width)
    :param bboxes: Tensor of shape (batch_size, num_boxes, 4)
    """
    # bboxes= list(bboxes[0]
    images, bboxes = batch[0], batch[1]
    
    # Convert tensor to numpy array for plotting
    images_np = images.numpy()*255
    
    print(bboxes)
    for i in range(images.size(0)):
        plt.figure(figsize=(10,10))

        image = np.transpose(images_np[i], (1, 2, 0)) # Convert to (height, width, channels)
        plt.imshow(image)
        
        
        x1, y1, x2, y2 = bboxes[i][1:]
        rect = patches.Rectangle((x1, y1), x2-x1, y2-y1, linewidth=1, edgecolor='r', facecolor='none')
        plt.gca().add_patch(rect)
        
        plt.axis('off')
        plt.show()


class ContrastiveLoss(nn.Module):
    
    '''
    margin - величина расстояния между позитивными и негативными образцами, которой мы пытаетмя добиться т.е. при лоссе, равном 0, 
    расстояние от анкерного объекта до позитивного, будет на margin меньше, чем расстояние от анкерного до негативного
    
    emb_size - размер эмбеддинга, поступающего на вход
    average - bool, способ агрегации функции потерь, если True, то среднее, 
                                                     если False, то сумма  
    '''
    
    def __init__(self, margin=2, average=True):
        super().__init__()
        
        self.margin = margin
        self.average = average
        
    def forward(self, anchor, x, similarity):

        '''
        similarity - метка класса, если 1, то x и анкер - один и тот же человек, 
                                   если 0, то x и анкер - разные люди,
        '''
        
        distance = ((anchor-x)**2).sum(axis=1).sqrt()
        
        result = similarity*distance**2 + (1-similarity)*F.relu(self.margin-distance)**2
        return result.mean() if self.average else result.sum()
    

class TripletLoss(nn.Module):
    
    '''
    margin - величина расстояния между позитивными и негативными образцами, которой мы пытаетмя добиться т.е. при лоссе, равном 0, 
    расстояние от анкерного объекта до позитивного, будет на margin меньше, чем расстояние от анкерного до негативного
    
    emb_size - размер эмбеддинга, поступающего на вход
    average - bool, способ агрегации функции потерь, если True, то среднее, если False, то сумма  
    
    '''
    def __init__(self, emb_size = 512, margin=2, average=True):
        super().__init__()
        
        self.margin = margin
        self.average = average
        self.emb_size = emb_size
        
    def forward(self, anchor, pos, neg):
        anchor, pos, neg = anchor.view([-1, self.emb_size]), pos.view([-1, self.emb_size]), neg.view([-1, self.emb_size])
        
        positive_dist = ((anchor-pos)**2).sum(axis=1)
        negative_dist = ((anchor-neg)**2).sum(axis=1)
        
        result = F.relu(positive_dist-negative_dist+self.margin)
        return result.mean() if self.average else result.sum()


def validate_model(model, test_dataloader, loss_fn, device):
    model.eval()  # Переключение модели в режим оценки
    total_loss = 0.0
    with torch.no_grad():  # Выключение вычисления градиентов
        for sample in test_dataloader:
            img, box = sample[0].to(device), sample[1].to(device)
            pred = model(img)
            loss = loss_fn(pred, box)
            total_loss += loss.item()
    
    avg_loss = total_loss / len(test_dataloader)  # Средняя потеря за эпоху
    model.train()  # Вернуть модель в режим обучения
    return avg_loss


def validate_model_rec(model, test_dataloader, loss_fn, device):
    # модель для валидации при обучении triplet модели
    model.eval() 
    total_loss = 0.0
    with torch.no_grad(): 
        for sample in test_dataloader:
            ans, pos, neg = sample 
            preds = model(ans.to(device), pos.to(device), neg.to(device))
            loss = loss_fn(*preds)
            total_loss += loss.item()
    
    avg_loss = total_loss / len(test_dataloader) 
    model.train()  
    return avg_loss


class EarlyStopping:
    def __init__(self, patience=5, min_delta=0):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_loss = None
        self.early_stop = False
    
    def __call__(self, val_loss):
        if self.best_loss is None:
            self.best_loss = val_loss
        elif val_loss > self.best_loss - self.min_delta:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_loss = val_loss
            self.counter = 0


def get_models_with_weights():
    """
    Инициализирует и загружает предобученные веса для моделей детекции и распознавания.

    Эта функция создает экземпляр класса InspectorGadjet в качестве модели детекции,
    загружает предобученные веса для модели детекции и устанавливает ее в режим оценки.

    Также создается модель EfficientNetB1 с измененным классификатором для распознавания,
    создается модель Triplet, использующая измененный EfficientNetB1, загружаются предобученные
    веса для модели распознавания и устанавливаются в режим оценки.

    Параметры:
        Нет

    Возвращает:
        tuple: Кортеж, содержащий модель детекции (экземпляр InspectorGadjet) и
        часть модели распознавания (кодировщик Triplet модели).
    """

    # задаем тип модели через класс
    det_model = models.InspectorGadjet()

    model_state_dict = torch.load(config['path_to_detection_weights'], map_location=torch.device('cpu'))['model_state_dict']
    det_model.load_state_dict(model_state_dict)
    det_model.eval()


    # задаем тип модели через класс
    conv = timm.create_model('efficientnet_b1', pretrained=False) # в данном случае берем готовую архитекуру
    conv.classifier = nn.Linear(conv.classifier.in_features, 512) # меняем архитектуру под нашу задачу
    rec_model = models.Triplet(conv)

    model_state_dict = torch.load(config['path_to_recognition_weights'], map_location=torch.device('cpu'))['model_state_dict']
    rec_model.load_state_dict(model_state_dict)
    rec_model.eval()
    

    print('Successfully loaded weights')
    return det_model, rec_model.encoder # возвращаем только encoder модели recognition, так как нам нужен только он