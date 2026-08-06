package com.doublechaintech.onlinebookstoreservice.book;

import com.doublechaintech.onlinebookstoreservice.Constants;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import io.teaql.core.Audited;
import io.teaql.core.BaseEntity;
import io.teaql.core.EntityStatus;
import io.teaql.core.FrameworkInternal;
import io.teaql.core.RemoteInput;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Objects;

/**
 * [TEAQL AI WARNING]
 * TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
 * DO NOT GUESS METHOD NAMES!
 * The methods listed below are the ONLY valid ways to interact with this entity.
 * If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
 * Read the method signatures in this file before proceeding.
 */
public class Book extends BaseEntity implements RemoteInput {
    public static String INTERNAL_TYPE = "Book";

    public static final String TITLE_PROPERTY = "title";
    public static final String AUTHOR_PROPERTY = "author";
    public static final String ISBN_PROPERTY = "isbn";
    public static final String PRICE_PROPERTY = "price";
    public static final String STOCK_COUNT_PROPERTY = "stockCount";
    public static final String CREATE_TIME_PROPERTY = "createTime";
    public static final String UPDATE_TIME_PROPERTY = "updateTime";
    public static final String BOOKSTORE_PROPERTY = "bookstore";
    public static final String CATEGORY_PROPERTY = "category";
    private String title;
    private String author;
    private String isbn;
    private BigDecimal price;
    private Integer stockCount;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
    private Bookstore bookstore;
    private BookCategory category;

    public String getTitle(){
        return this.title;
    }
    public String getAuthor(){
        return this.author;
    }
    public String getIsbn(){
        return this.isbn;
    }
    public BigDecimal getPrice(){
        return this.price;
    }
    public Integer getStockCount(){
        return this.stockCount;
    }
    public LocalDateTime getCreateTime(){
        return this.createTime;
    }
    public LocalDateTime getUpdateTime(){
        return this.updateTime;
    }
    public Bookstore getBookstore(){
        return this.bookstore;
    }
    public BookCategory getCategory(){
        return this.category;
    }
    public Book updateTitle(String title){
        title = (title == null ? null : title.trim());
        if(Objects.equals(this.title, title)){
            return this;
        }
        handleUpdate(TITLE_PROPERTY, getTitle(), title);
        this.title = title;
        return this;
    }
    public Book updateAuthor(String author){
        author = (author == null ? null : author.trim());
        if(Objects.equals(this.author, author)){
            return this;
        }
        handleUpdate(AUTHOR_PROPERTY, getAuthor(), author);
        this.author = author;
        return this;
    }
    public Book updateIsbn(String isbn){
        isbn = (isbn == null ? null : isbn.trim());
        if(Objects.equals(this.isbn, isbn)){
            return this;
        }
        handleUpdate(ISBN_PROPERTY, getIsbn(), isbn);
        this.isbn = isbn;
        return this;
    }
    public Book updatePrice(BigDecimal price){
        if(Objects.equals(this.price, price)){
            return this;
        }
        handleUpdate(PRICE_PROPERTY, getPrice(), price);
        this.price = price;
        return this;
    }
    public Book updateStockCount(Integer stockCount){
        if(Objects.equals(this.stockCount, stockCount)){
            return this;
        }
        handleUpdate(STOCK_COUNT_PROPERTY, getStockCount(), stockCount);
        this.stockCount = stockCount;
        return this;
    }
    public Book updateCreateTime(LocalDateTime createTime){
        if(Objects.equals(this.createTime, createTime)){
            return this;
        }
        handleUpdate(CREATE_TIME_PROPERTY, getCreateTime(), createTime);
        this.createTime = createTime;
        return this;
    }
    public Book updateUpdateTime(LocalDateTime updateTime){
        if(Objects.equals(this.updateTime, updateTime)){
            return this;
        }
        handleUpdate(UPDATE_TIME_PROPERTY, getUpdateTime(), updateTime);
        this.updateTime = updateTime;
        return this;
    }
    public Book updateBookstore(Bookstore bookstore){
        if(Objects.equals(this.bookstore, bookstore)){
            return this;
        }
        handleUpdate(BOOKSTORE_PROPERTY, getBookstore(), bookstore);
        this.bookstore = bookstore;
        return this;
    }
    protected Book updateCategory(BookCategory category){
        if(Objects.equals(this.category, category)){
            return this;
        }
        handleUpdate(CATEGORY_PROPERTY, getCategory(), category);
        this.category = category;
        return this;
    }
    public boolean isCategoryFiction(){
        return Objects.equals(getCategory(), Constants.BOOK_CATEGORY_FICTION);
    }

    public Book updateCategoryToFiction(){
        return updateCategory(Constants.BOOK_CATEGORY_FICTION);
    }
    public boolean isCategoryNonFiction(){
        return Objects.equals(getCategory(), Constants.BOOK_CATEGORY_NON_FICTION);
    }

    public Book updateCategoryToNonFiction(){
        return updateCategory(Constants.BOOK_CATEGORY_NON_FICTION);
    }
    public boolean isCategoryScience(){
        return Objects.equals(getCategory(), Constants.BOOK_CATEGORY_SCIENCE);
    }

    public Book updateCategoryToScience(){
        return updateCategory(Constants.BOOK_CATEGORY_SCIENCE);
    }
    public boolean isCategoryHistory(){
        return Objects.equals(getCategory(), Constants.BOOK_CATEGORY_HISTORY);
    }

    public Book updateCategoryToHistory(){
        return updateCategory(Constants.BOOK_CATEGORY_HISTORY);
    }

    public static Book refer(Long id){
        Book refer = new Book();
        refer.__internalSet("id", id);
        refer.set$status(EntityStatus.REFER);
        return refer;
    }
    @Override
    public String typeName(){
        return INTERNAL_TYPE;
    }

    public Book comment(String comment){
        this.setComment(comment);
        return this;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Audited<Book> auditAs(String action) {
        return super.auditAs(action);
    }

    // ===== Framework Internal: generated switch dispatch =====
    @Override
    @FrameworkInternal
    public void __internalSet(String property, Object value) {
        switch (property) {
            case "title": this.title = (value == null ? null : ((String)value).trim()); break;

            case "author": this.author = (value == null ? null : ((String)value).trim()); break;

            case "isbn": this.isbn = (value == null ? null : ((String)value).trim()); break;

            case "price": this.price = (BigDecimal) value; break;

            case "stockCount": this.stockCount = (Integer) value; break;

            case "createTime": this.createTime = (LocalDateTime) value; break;

            case "updateTime": this.updateTime = (LocalDateTime) value; break;

            case "bookstore": this.bookstore = (Bookstore) value; break;

            case "category": this.category = (BookCategory) value; break;

            default: super.__internalSet(property, value);
        }
    }

    @Override
    @FrameworkInternal
    public Object __internalGet(String property) {
        switch (property) {
            case "title": return this.title;
            case "author": return this.author;
            case "isbn": return this.isbn;
            case "price": return this.price;
            case "stockCount": return this.stockCount;
            case "createTime": return this.createTime;
            case "updateTime": return this.updateTime;
            case "bookstore": return this.bookstore;
            case "category": return this.category;
            default: return super.__internalGet(property);
        }
    }

}